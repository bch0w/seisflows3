#!/usr/bin/env python
"""
This script controls Seisflows.

This script needs to be run in a directory containing `parameters.yaml` which
should contain user defined paths and parameters to be used in the workflow
"""
import os
import sys
import argparse
from glob import glob

from seisflows.tools import unix, tools
from seisflows.config import config, tilde_expand, Dict, names
from seisflows.tools.tools import loadyaml


def get_args():
    """
    Get User defined arguments, or assign defaults

    :rtype: argparse.ArgumentParser()
    :return: User defined or default arguments
    """
    parser = argparse.ArgumentParser()

    # Positional arguments
    parser.add_argument("run", type=str, nargs="?",
                        choices=["submit", "clean", "resume", "debug",
                                 "restart", "check"],
                        help="task for Seisflows to perform")

    # Optional parameters
    parser.add_argument("-w", "--workdir", nargs="?", default=os.getcwd())
    parser.add_argument("-p", "--parameter_file", nargs="?",
                        default="parameters.yaml")

    return parser.parse_args()


def parse_null(parameters):
    """
    Seisflows was written in such a way that excluding parameters from the 
    parameter file would enforce default values. This becomes confusing however 
    because then the User needs to look at the definitions in the check()
    functions of each module to determine which parameters they want to exclude.

    Rather than rewrite this system, we allow the User to set parameters to 
    None, null, '', etc. This function sanitizes those inputs before handing 
    them over to Seisflows. This allows for full parameter files that include 
    all options that also works with the machinery of Seisflows

    This function also enforces a few string formats 

    :type parameters: dict
    :param parameters: dict of parameters to parse
    :rtype: dict
    :return: parameters that have been sanitized of all null values
    """
    # Copy the dictionary to get around deleting keys while iterating
    parsed_parameters = dict(parameters)
    for key, item in parameters.items():
        # Search for all None and "" items, ignore bools, 0's etc.
        if not item and isinstance(item, (type(None), str)):
            del parsed_parameters[key]
        elif key == "LINESEARCH":
            parsed_parameters[key] = item.capitalize()

    return parsed_parameters


def setup(precheck=True):
    """
    Common setup for multiple functions, parses the parameter and paths,
    places them into sys.modules for global accessibiliy.
    """
    args = get_args()

    # Check if the filepaths exist
    if not os.path.exists(args.parameter_file):
        raise FileNotFoundError(f"Parameter file not found: "
                                f"{args.parameter_file}")

    # Register parameters
    parameters = loadyaml(args.parameter_file)
    if precheck:
        precheck_parameters(parameters)
    parameters = parse_null(parameters)
    sys.modules['seisflows_parameters'] = Dict(parameters)

    # Register paths, expand to relative paths to absolute
    paths = tilde_expand(parameters['PATHS'])
    paths = {key: os.path.abspath(path) for key, path in paths.items()}
    sys.modules['seisflows_paths'] = Dict(paths)

    return args, paths, parameters


def precheck_parameters(par):
    """
    Print important arguments before beginning a workflow. This will ensure that
    the User is aware of how key arguments are set that will have major affect
    on the workflow.
    """
    msg = f"""
      Beginning workflow "{par['TITLE']}"...
          WORKFLOW: {par['WORKFLOW']}
          BEGIN: {par['BEGIN']}
          END: {par['END']}
          RESUME_FROM: {par['RESUME_FROM']}
          STOP_AFTER: {par['STOP_AFTER']}
          NTASK: {par['NTASK']}
          WALLTIME: {par['WALLTIME']}
          CASE: {par['CASE']}
          SMOOTH H,V: {par['SMOOTH_H']}, {par['SMOOTH_V']}
          """
    print(msg)
    check = input("Continue? (y/[n]): ")
    if check != "y":
        sys.exit(-1)


def submit():
    """
    Submit the workflow for the first time
    """
    args, paths, parameters = setup()

    # Check that paths exist
    paths_dont_exist = []
    for key, path in paths.items():
        if (key in ["OUTPUT", "SCRATCH"]) or (path == ""):
            continue
        if not os.path.exists(path):
            paths_dont_exist.append(path)
    if paths_dont_exist:
        print("\nThe following paths do not exist:\n")
        for path_ in paths_dont_exist:
            print(f"\t{path_}")
        print("\n")
        sys.exit()

    # If paths exist, pass to modules
    sys.modules["seisflows_paths"] = Dict(paths)
    unix.mkdir(args.workdir)
    unix.cd(args.workdir)

    # Submit workflow
    config()  # Instantiate all modules and check their parameters
    workflow = sys.modules["seisflows_workflow"]
    system = sys.modules["seisflows_system"]

    system.submit(workflow)


def resume():
    """
    Resume a previously started workflow by loading the module pickle files and
    submitting the workflow 
    """
    args, paths, parameters = setup()

    # Work directory should already be created
    unix.cd(args.workdir)

    # Reload objects from Pickle files
    for name in names:
        fullfile = os.path.join(args.workdir, "output", f"seisflows_{name}.p")
        sys.modules[f"seisflows_{name}"] = tools.loadobj(fullfile)

    # Check parameters
    for name in names:
        sys.modules[f"seisflows_{name}"].check()

    workflow = sys.modules["seisflows_workflow"]
    system = sys.modules["seisflows_system"]

    system.submit(workflow)


def debug():
    """
    A debug mode that reloads the system modules and starting an IPython
    debugger allowing exploration of the package space in an interactive 
    environment.
    """
    args, paths, parameters = setup(precheck=False)

    # Work directory should already be created
    unix.cd(args.workdir)

    # Reload objects from Pickle files
    for name in names:
        fullfile = os.path.join(args.workdir, "output", f"seisflows_{name}.p")
        sys.modules[f"seisflows_{name}"] = tools.loadobj(fullfile)

    # Check parameters
    for name in names:
        sys.modules[f"seisflows_{name}"].check()

    workflow = sys.modules["seisflows_workflow"]
    system = sys.modules["seisflows_system"]

    # Prematurely distribute modules for easier debugging
    PATH = sys.modules["seisflows_paths"]
    PAR = sys.modules["seisflows_parameters"]
    system = sys.modules["seisflows_system"]
    solver = sys.modules["seisflows_solver"]
    optimize = sys.modules["seisflows_optimize"]
    preprocess = sys.modules["seisflows_preprocess"]
    postprocess = sys.modules["seisflows_postprocess"]

    # Import debugging options. The following lines will be displayed to console
    import ipdb
    from IPython import embed
    # This is Seisflows' debug mode.
    ipdb.set_trace(context=5)
    embed(colors="Neutral")
    # type 'n' to access a more useful IPython debugger.
    # type 'workflow.checkpoint()' to save any changes made here.


def clean(workdir=None):
    """
    Clean the working directory

    :type workdir: str
    :param workdir: working directory to clean, defaults to cwd
    """
    if workdir is None:
        workdir = os.getcwd()
        
    check = input("\nThis will remove all workflow objects, leaving only the "
                  "parameter file.\nAre you sure you want to clean? (y/[n]): ")
    if check == "y":
        for fid in glob(os.path.join(workdir, "output*")):
            unix.rm(fid)
        for fid in glob(os.path.join(workdir, "*log*")):
            unix.rm(fid)
        unix.rm(os.path.join(workdir, "scratch"))


def main():
    """
    Main entry point into the SeisFlows package
    """
    args_ = get_args()
    if args_.run == "submit":
        submit()
    elif args_.run == "resume":
        resume()
    elif args_.run == "debug":
        debug()
    elif args_.run == "clean":
        clean(args_.workdir)
    elif args_.run == "restart":
        clean(args_.workdir)
        submit()

if __name__ == "__main__":
    main()
        