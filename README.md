# GraphIE

## Model Outputs
### Overview
To ensure the files are correct, I did the following checks on Apr 2, 2019.

|Conll03 Dev/Test|# docs|GraphIE (best)|SeqIE (best)|
|---|---|---|---|
|Test|231|92.02|91.57|
|Dev|216|94.90|94.66|

### Outputs
|Conll03 Dev/Test|GraphIE (best)|SeqIE (best)|
|---|---|---|
|Test|[Output](outputs/conll03_GraphIE/11131230r10_test) (92.02)|(91.57)|
|Dev|[Output](outputs/conll03_GraphIE/11131230r10_dev) (94.90)|(94.66)|

### Specs
- The dev output is saved in the last epoch.
- The test output is saved in the epoch with the highest F1 score on the dev data.

## Code (FYI)
To get a better understanding of how the outputs are saved, please refer to the main [code file](code/examples/multi_runs_conll.py).



