#!/usr/bin/env python
from __future__ import print_function

__author__ = 'jindi'
"""
Implementation of Bi-directional LSTM-CNNs-CRF model for NER.
"""

import sys
import os

sys.path.append(".")
sys.path.append("..")
homedir = os.path.expanduser('~')

import time
import argparse
import uuid

import numpy as np
import torch
import torch.nn as nn
from torch.optim import Adam, SGD
from neuronlp2.io import get_logger, conll03_data, CoNLL03Writer
from neuronlp2.models import BiRecurrentConvCRF, BiWeightDropRecurrentConvCRF
from neuronlp2 import utils

uid = uuid.uuid4().hex[:6]


# evaluate the NER score using official scorer from CONLL-2003 competition
def evaluate(output_file, score_file, evaluate_raw_format=False, o_tag='O'):
    if evaluate_raw_format:
        os.system("examples/eval/conll03eval.v2 -r -o %s < %s > %s" % (o_tag, output_file, score_file))
    else:
        os.system("examples/eval/conll03eval.v2 -o %s < %s > %s" % (o_tag, output_file, score_file))
    with open(score_file, 'r') as fin:
        fin.readline()
        line = fin.readline()
        fields = line.split(";")
        acc = float(fields[0].split(":")[1].strip()[:-1])
        precision = float(fields[1].split(":")[1].strip()[:-1])
        recall = float(fields[2].split(":")[1].strip()[:-1])
        f1 = float(fields[3].split(":")[1].strip())
    return acc, precision, recall, f1


def adjust_learning_rate(optimizer, lr):
    """Sets the learning rate""" 
    for param_group in optimizer.param_groups:
        param_group['lr'] = lr


def main():
    # Arguments parser
    parser = argparse.ArgumentParser(description='Tuning with DNN Model for NER')
    # Model Hyperparameters
    parser.add_argument('--mode', choices=['RNN', 'LSTM', 'GRU'], help='architecture of rnn', default='LSTM')
    parser.add_argument('--encoder_mode', choices=['cnn', 'lstm'], help='Encoder type for sentence encoding', default='lstm')
    parser.add_argument('--char_method', choices=['cnn', 'lstm'], help='Method to create character-level embeddings', required=True)
    parser.add_argument('--hidden_size', type=int, default=128, help='Number of hidden units in RNN for sentence level')
    parser.add_argument('--char_hidden_size', type=int, default=30, help='Output character-level embeddings size')
    parser.add_argument('--char_dim', type=int, default=30, help='Dimension of Character embeddings')
    parser.add_argument('--tag_space', type=int, default=0, help='Dimension of tag space')
    parser.add_argument('--num_layers', type=int, default=1, help='Number of layers of RNN')
    parser.add_argument('--dropout', choices=['std', 'weight_drop'], help='Dropout method', default='weight_drop')
    parser.add_argument('--p_em', type=float, default=0.33, help='dropout rate for input embeddings')
    parser.add_argument('--p_in', type=float, default=0.33, help='dropout rate for input of RNN model')
    parser.add_argument('--p_rnn', nargs=2, type=float, required=True, help='dropout rate for RNN')
    parser.add_argument('--p_out', type=float, default=0.33, help='dropout rate for output layer')
    parser.add_argument('--bigram', action='store_true', help='bi-gram parameter for CRF')

    # Data loading and storing params
    parser.add_argument('--embedding_dict', help='path for embedding dict')
    parser.add_argument('--dataset_name', type=str, default='alexa', help='Which dataset to use')
    parser.add_argument('--train', type=str, required=True, help='Path of train set')  
    parser.add_argument('--dev', type=str, required=True, help='Path of dev set')  
    parser.add_argument('--test', type=str, required=True, help='Path of test set')  
    parser.add_argument('--results_folder', type=str, default='results', help='The folder to store results')
    parser.add_argument('--tmp_folder', type=str, default='tmp', help='The folder to store tmp files')
    parser.add_argument('--alphabets_folder', type=str, default='data/alphabets', help='The folder to store alphabets files')
    parser.add_argument('--result_file_name', type=str, default='hyperparameters_tuning', help='File name to store some results')
    parser.add_argument('--eval_filename', type=str, required=True, help='File name to store the predictions for evaluation')
    parser.add_argument('--result_file_path', type=str, default='results/hyperparameters_tuning', help='File name to store some results')

    # Training parameters
    parser.add_argument('--cuda', action='store_true', help='whether using GPU')
    parser.add_argument('--num_epochs', type=int, default=100, help='Number of training epochs')
    parser.add_argument('--batch_size', type=int, default=16, help='Number of sentences in each batch')
    parser.add_argument('--learning_rate', type=float, default=0.001, help='Base learning rate')
    parser.add_argument('--decay_rate', type=float, default=0.95, help='Decay rate of learning rate')
    parser.add_argument('--schedule', type=int, default=3, help='schedule for learning rate decay')
    parser.add_argument('--gamma', type=float, default=0.0, help='weight for l2 regularization')
    parser.add_argument('--max_norm', type=float, default=1., help='Max norm for gradients')
    parser.add_argument('--gpu_id', type=int, nargs='+', required=True, help='which gpu to use for training')

    # Misc
    parser.add_argument('--embedding', choices=['glove', 'senna', 'alexa'], help='Embedding for words', required=True)
    parser.add_argument('--restore', action='store_true', help='whether restore from stored parameters')
    parser.add_argument('--save_checkpoint', type=str, default='', help='the path to save the model')
    parser.add_argument('--o_tag', type=str, default='O', help='The default tag for outside tag')
    parser.add_argument('--unk_replace', type=float, default=0., help='The rate to replace a singleton word with UNK')
    parser.add_argument('--evaluate_raw_format', action='store_true', help='The tagging format for evaluation')

    args = parser.parse_args()

    logger = get_logger("NERCRF")

    # rename the parameters
    mode = args.mode
    encoder_mode = args.encoder_mode
    train_path = args.train
    dev_path = args.dev
    test_path = args.test
    num_epochs = args.num_epochs
    batch_size = args.batch_size
    hidden_size = args.hidden_size
    char_hidden_size = args.char_hidden_size
    char_method = args.char_method
    learning_rate = args.learning_rate
    momentum = 0.9
    decay_rate = args.decay_rate
    gamma = args.gamma
    max_norm = args.max_norm
    schedule = args.schedule
    dropout = args.dropout
    p_em = args.p_em
    p_rnn = tuple(args.p_rnn)
    p_in = args.p_in
    p_out = args.p_out
    unk_replace = args.unk_replace
    bigram = args.bigram
    embedding = args.embedding
    embedding_path = args.embedding_dict
    dataset_name = args.dataset_name
    result_file_name = args.result_file_name
    evaluate_raw_format = args.evaluate_raw_format
    o_tag = args.o_tag
    restore = args.restore
    save_checkpoint = args.save_checkpoint
    gpu_id = args.gpu_id
    results_folder = args.results_folder
    tmp_folder = args.tmp_folder
    alphabets_folder = args.alphabets_folder
    use_elmo = False
    p_em_vec = 0.
    result_file_path = args.result_file_path
    eval_filename = args.eval_filename

    score_file = "%s/score_gpu_%s" % (tmp_folder, '-'.join(map(str, gpu_id)))

    if not os.path.exists(results_folder):
        os.makedirs(results_folder)
    if not os.path.exists(tmp_folder):
        os.makedirs(tmp_folder)  
    if not os.path.exists(alphabets_folder):
        os.makedirs(alphabets_folder)

    embedd_dict, embedd_dim = utils.load_embedding_dict(embedding, embedding_path)

    logger.info("Creating Alphabets")
    word_alphabet, char_alphabet, ner_alphabet = conll03_data.create_alphabets("{}/{}/".format(alphabets_folder, dataset_name), train_path, data_paths=[dev_path, test_path],
                                                                 embedd_dict=embedd_dict, max_vocabulary_size=50000)

    logger.info("Word Alphabet Size: %d" % word_alphabet.size())
    logger.info("Character Alphabet Size: %d" % char_alphabet.size())
    logger.info("NER Alphabet Size: %d" % ner_alphabet.size())

    logger.info("Reading Data")
    device = torch.device('cuda') if args.cuda else torch.device('cpu')
    print(device)

    data_test = conll03_data.read_data_to_tensor(test_path, word_alphabet, char_alphabet, ner_alphabet, device=device)
    num_data = sum(data_test[1])
    num_labels = ner_alphabet.size()

    writer = CoNLL03Writer(word_alphabet, char_alphabet, ner_alphabet)

    def construct_word_embedding_table():
        scale = np.sqrt(3.0 / embedd_dim)
        table = np.empty([word_alphabet.size(), embedd_dim], dtype=np.float32)
        table[conll03_data.UNK_ID, :] = np.random.uniform(-scale, scale, [1, embedd_dim]).astype(np.float32)
        oov = 0
        for word, index in word_alphabet.items():
            if word in embedd_dict:
                embedding = embedd_dict[word]
            elif word.lower() in embedd_dict:
                embedding = embedd_dict[word.lower()]
            else:
                embedding = np.random.uniform(-scale, scale, [1, embedd_dim]).astype(np.float32)
                oov += 1
            table[index, :] = embedding
        print('oov: %d' % oov)
        return torch.from_numpy(table)

    word_table = construct_word_embedding_table()
    logger.info("constructing network...")

    char_dim = args.char_dim
    window = 3
    num_layers = args.num_layers
    tag_space = args.tag_space
    initializer = nn.init.xavier_uniform_
    if args.dropout == 'std':
        network = BiRecurrentConvCRF(embedd_dim, word_alphabet.size(), char_dim, char_alphabet.size(), char_hidden_size, window, mode, encoder_mode, hidden_size, num_layers, num_labels,
                                     tag_space=tag_space, embedd_word=word_table, use_elmo=use_elmo, p_em_vec=p_em_vec, p_em=p_em, p_in=p_in, p_out=p_out, p_rnn=p_rnn, bigram=bigram, initializer=initializer)
    elif args.dropout == 'var':
        network = BiVarRecurrentConvCRF(embedd_dim, word_alphabet.size(), char_dim, char_alphabet.size(), char_hidden_size, window, mode, encoder_mode, hidden_size, num_layers, num_labels,
                                        tag_space=tag_space, embedd_word=word_table, use_elmo=use_elmo, p_em_vec=p_em_vec, p_em=p_em, p_in=p_in, p_out=p_out, p_rnn=p_rnn, bigram=bigram, initializer=initializer)
    else:
        network = BiWeightDropRecurrentConvCRF(embedd_dim, word_alphabet.size(), char_dim, char_alphabet.size(), char_hidden_size, window, mode, encoder_mode, hidden_size, num_layers, num_labels,
                                        tag_space=tag_space, embedd_word=word_table, p_em=p_em, p_in=p_in, p_out=p_out, p_rnn=p_rnn, bigram=bigram, initializer=initializer)

    # whether restore from trained model
    if restore:
        network.load_state_dict(torch.load(save_checkpoint+'_best.pth')) # load trained model
    
    network = network.to(device)

    logger.info("Network: %s, encoder_mode=%s, num_layer=%d, hidden=%d, char_hidden_size=%d, char_method=%s, tag_space=%d, crf=%s" % \
        (mode, encoder_mode, num_layers, hidden_size, char_hidden_size, char_method, tag_space, 'bigram' if bigram else 'unigram'))
    logger.info("dropout(in, out, rnn): (%.2f, %.2f, %s)" % (p_in, p_out, p_rnn))

    num_batches = num_data // batch_size + 1
    test_f1 = 0.0
    test_acc = 0.0
    test_precision = 0.0
    test_recall = 0.0

    # evaluate performance on dev data
    with torch.no_grad():
        network.eval()

        # evaluate on test data when better performance detected
        writer.start(eval_filename)

        for batch in conll03_data.iterate_batch_tensor(data_test, batch_size):
            _, word, char, labels, masks, lengths = batch
            preds, _ = network.decode(_, word, char, target=labels, mask=masks, leading_symbolic=conll03_data.NUM_SYMBOLIC_TAGS)
            writer.write(word.cpu().numpy(), preds.cpu().numpy(), labels.cpu().numpy(), lengths.cpu().numpy())
        writer.close()
        test_acc, test_precision, test_recall, test_f1 = evaluate(eval_filename, score_file, evaluate_raw_format, o_tag)   

    with open(result_file_path, 'a') as ofile:
        ofile.write("test acc: %.2f%%, precision: %.2f%%, recall: %.2f%%, F1: %.2f%%\n" % (test_acc, test_precision, test_recall, test_f1))
    print('Evaluation finished!')


if __name__ == '__main__':
    main()
