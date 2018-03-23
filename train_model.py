"""
Description:
    This script builds the model and trains it using user-specified input data.

Output:
    Saves model to a user-specified output file.

Usage:
    train_model.py <import-module> <model-class-name> <lr>
        <paths-yml> <train-model-yml>
        [-s | --stdout] [-v | --verbose]
    train_model.py -h | --help

Options:
    -h --help               Show this screen.

    <import-module>         Import the module containing the model
    <model-class-name>      Must be a model class in the imported module
    <lr>                    Choose the optimizer's learning rate
    <paths-yml>             Input data and output filepaths
    <train-model-yml>       Model-specific parameters
    -s --stdout             Will also output logging information to stdout
                            [default: False]
    -v --verbose            Include debug messages in logging information
                            [default: False]
"""
import importlib
import logging
import os
import sys
from time import strftime, time

from docopt import docopt
import torch

from model_controller import ModelController
from sampler import IntervalsSampler
#from sampler import ChromatinFeaturesSampler
from utils import read_yaml_file

if __name__ == "__main__":
    arguments = docopt(
        __doc__,
        version="1.0")

    import_model_from = arguments["<import-module>"]
    model_class_name = arguments["<model-class-name>"]
    use_module = importlib.import_module(import_model_from)
    model_class = getattr(use_module, model_class_name)

    lr = float(arguments["<lr>"])

    paths = read_yaml_file(
        arguments["<paths-yml>"])
    train_model = read_yaml_file(
        arguments["<train-model-yml>"])

    ##################################################
    # PATHS
    ##################################################
    dir_path = paths["dir_path"]
    files = paths["files"]
    genome_fasta = os.path.join(
        dir_path, files["genome"])
    genomic_features = os.path.join(
        dir_path, files["genomic_features"])
    coords_only = os.path.join(
        dir_path, files["sample_from_regions"])
    distinct_features = os.path.join(
        dir_path, files["distinct_features"])

    output_dir = paths["output_dir"]
    os.makedirs(output_dir, exist_ok=True)

    current_run_output_dir = os.path.join(
        output_dir, strftime("%Y-%m-%d-%H-%M-%S"))
    os.makedirs(current_run_output_dir)

    ##################################################
    # TRAIN MODEL PARAMETERS
    ##################################################
    sampler_info = train_model["sampler"]
    model_controller_info = train_model["model_controller"]

    ##################################################
    # OTHER ARGS
    ##################################################
    to_stdout = arguments["--stdout"]
    verbose = arguments["--verbose"]

    log = logging.getLogger("selene")
    if verbose:
        log.setLevel(logging.DEBUG)
    else:
        log.setLevel(logging.INFO)

    formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")

    log_output = os.path.join(current_run_output_dir, "train_model_log.out")
    file_handle = logging.FileHandler(log_output)
    file_handle.setFormatter(formatter)
    log.addHandler(file_handle)

    if to_stdout:
        stream_handle = logging.StreamHandler(sys.stdout)
        stream_handle.setFormatter(formatter)
        log.addHandler(stream_handle)

    t_i = time()
    feature_thresholds = None
    if "specific_feature_thresholds" in sampler_info:
        feature_thresholds = sampler_info["specific_feature_thresholds"]
        del sampler_info["specific_feature_thresholds"]
    else:
        feature_thresholds = None
    if "default_threshold" in sampler_info:
        if feature_thresholds:
            feature_thresholds["default"] = \
                sampler_info["default_threshold"]
        else:
            feature_thresholds = sampler_info["default_threshold"]
        del sampler_info["default_threshold"]

    if feature_thresholds:
        sampler_info["feature_thresholds"] = feature_thresholds

    sampler = IntervalsSampler(
        genome_fasta,
        genomic_features,
        distinct_features,
        coords_only,
        **sampler_info)

    t_i_model = time()
    torch.manual_seed(1337)
    torch.cuda.manual_seed_all(1337)

    model = model_class(sampler.sequence_length, sampler.n_features)
    print(model)

    checkpoint_info = model_controller_info["checkpoint"]
    checkpoint_resume = checkpoint_info["resume"]
    checkpoint = None
    if checkpoint_resume:
        checkpoint_file = checkpoint_info["model_file"]
        log.info("Resuming training from checkpoint {0}.".format(
            checkpoint_file))
        checkpoint = torch.load(checkpoint_file)
        model.load_state_dict(checkpoint["state_dict"])
        model.eval()

    criterion = use_module.criterion()
    optimizer_class, optimizer_args = use_module.get_optimizer(lr)

    t_f_model = time()
    log.debug(
        "Finished initializing the {0} model from module {1}: {2} s".format(
            model.__class__.__name__,
            import_model_from,
            t_f_model - t_i_model))

    log.info(model)
    log.info(optimizer_args)

    batch_size = model_controller_info["batch_size"]
    n_epochs = model_controller_info["n_epochs"]
    n_steps_per_epoch = model_controller_info["n_steps_per_epoch"]

    runner = ModelController(
        model, sampler, criterion, optimizer_class, optimizer_args,
        batch_size, n_steps_per_epoch,
        current_run_output_dir,
        checkpoint_resume=checkpoint,
        **model_controller_info["optional_args"])

    log.info("Training model: {0} epochs, {1} batch size.".format(
        n_epochs, batch_size))
    runner.train_and_validate(n_epochs)

    t_f = time()
    log.info("./train_model.py completed in {0} s.".format(t_f - t_i))
