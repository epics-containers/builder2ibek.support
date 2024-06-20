#!/bin/env dls-python

"""
Diamond Light Source specific script to convert IOC builder classes from
etc/builder.py into **ibek.support.yaml files.

TO work on this project it is very helpful to be able to run in the vscode
debugger. HOW TO DO THIS:

- Downgrade the Python Extension in vscode to 2021.9.1246542782
- Use the debug launcher called builder2ibek
- change the filename (and other args)that is passed in the debug launcher
  - by editing .vscode/launch.json
"""

import argparse
import inspect
import os
import re
import sys

# import required modules
from pkg_resources import require

require("iocbuilder")
require("dls_dependency_tree")
require("ruamel.yaml")
require("mock")
from ruamel.yaml.scalarstring import PreservedScalarString

from dls_dependency_tree import dependency_tree  # noqa: E402 isort:skip
from iocbuilder import ParseEtcArgs, configure, device  # noqa: E402 isort:skip
from iocbuilder.recordset import RecordsSubstitutionSet  # noqa: E402 isort:skip
from mock import MagicMock  # noqa: E402 isort:skip
from ruamel.yaml import YAML  # noqa: E402 isort:skip
from ruamel.yaml.comments import CommentedMap  # noqa: E402 isort:skip


# regular expressions for extracting information from builder classes
class_name_re = re.compile(r"(?:type|class) '(.*)'")
is_int_re = re.compile(r"[-+]?\d+$")
is_float_re = re.compile(r"[-+]?\d*\.\d+([eE][-+]?\d+)?$")

# this monster regex finds strings between '' or "" (oh boy!)
extract_printed_strings_re = re.compile(r"([\"'])((?:\\\1|(?:(?!\1))[\S\s])*)(?:\1)")
# extract print with \ separated lines with second group containing remaining lines
extract_multiline_print_re = re.compile(
    r" *\(? *((?:[\"'][\S\s]*\\[\n]+[^\n]+)|.+)(?:\.format *\([^\)]+\))?([\S\s]*)"
)
# match substitution fields in print statements e.g. %(name)s or {name:s} etc
macros_re = re.compile(r"(?:(?:{)|(?:%\())([^:\)}]*)(?:(?:(?::.)?})|(?:\).))")
# replace matched fields with jinja2 style macros
macro_to_jinja_re = r"{{\1}}"

MISSING = "# TODO - MISSING ARGS: "
NON_PRINT = "\n # WARNING - non print commands in Initialise not parsed"
DELETE_PARAMS = ["gda_name", "gda_desc", "EMPTY"]

# global argument override dictionaries
arg_value_overrides = {}
mock_overrides = {}


class ArgInfo:
    """
    A class to consume builder ArgInfo objects and extract useful information
    to construct an equivalent ibek definition YAML tree.S
    """

    description_re = re.compile(r"(.*)\n<(?:type|class)")
    name_re = re.compile(r"iocbuilder\.modules\.(?:.*)\.(.*)")
    arg_num = 1

    def __init__(self, name, unique_name, description):
        """
        Unique name is the argument that uniquely identifies
        """
        # unique name for the builder class
        self.unique_name = unique_name

        # CommentedMap of CommentedMap args to be used in the YAML
        self.yaml_args = CommentedMap()
        # the root of the definition in yaml that holds above yaml_args
        self.yaml_defs = CommentedMap()
        # set of args and values to use for instantiating a builder object
        self.builder_args = {}
        # list of all the arg names only (across multiple add_arg_info)
        self.all_args = []

        # The arginfo we will consume when calling add_arg_info
        self.arginfo = None

        if description:
            desc = description.strip()
        else:
            desc = "TODO:ADD DESCRIPTION"

        print(name)
        self.yaml_defs["name"] = self.name_re.findall(name)[0]
        self.yaml_defs["description"] = PreservedScalarString(desc)
        self.yaml_defs["parameters"] = self.yaml_args

    def add_arg_info(self, arginfo):
        """
        Consume an ArgInfo object
        """
        self.arginfo = arginfo
        # we reset builder args for each new ArgInfo - this is because
        # we call once for builder object __init__ and once for each
        # database substitution template. For each we want to record the
        # args for that particular item.
        self.builder_args = {}
        self._interpret()

    def _interpret(self):
        # iterate over all args in the ArgInfo, generating Args in the YAML
        # and builder object args
        all_names = (
            self.arginfo.required_names
            + self.arginfo.default_names
            + self.arginfo.optional_names
        )

        for arg_name in all_names:
            details = self.arginfo.descriptions[arg_name]

            # extract the type and default value
            if arg_name in self.arginfo.default_names:
                index = self.arginfo.default_names.index(arg_name)
                default = self.arginfo.default_values[index]
            else:
                default = None

            typ, default = self.make_arg(arg_name, details, default)

            # remove gda_name and desc as redundant
            if arg_name in ["gda_name", "gda_desc"]:
                continue

            # extract the description
            matches = self.description_re.findall(details.desc)
            if len(matches) > 0:
                description_str = matches[0]
            else:
                description_str = "TODO: ADD DESCRIPTION"

            def make_enum(value):
                value = str(value).strip().strip('"')
                return str(value)

            if arg_name not in self.all_args:
                new_yaml_arg = CommentedMap()
                new_yaml_arg["type"] = typ
                new_yaml_arg["description"] = PreservedScalarString(description_str)
                if default is not None:
                    new_yaml_arg["default"] = default
                if typ == "enum":
                    new_yaml_arg["values"] = CommentedMap()
                    for label in details.labels:
                        new_yaml_arg["values"][make_enum(label)] = None
                # coerce type of args that have default strings which are ints or reals
                if arg_name == "tag_idx":
                    print("XXX tag_idx {default}")
                if typ == "str" and default:
                    try:
                        i = int(default)
                        new_yaml_arg["default"] = i
                        new_yaml_arg["type"] = "int"
                    except ValueError:
                        try:
                            f = float(default)
                            new_yaml_arg["default"] = f
                            new_yaml_arg["type"] = "float"
                        except ValueError:
                            pass

                self.yaml_args[arg_name] = new_yaml_arg
                self.all_args.append(arg_name)

    def make_arg(self, name, details, default=None):
        """
        Work out the type and default value for an argument.
        Create a builder object arg entry with best guess for a value.
        Support overriding of the guessed values from the command line.
        """

        mock_over = mock_overrides.get(name, {})

        if name == self.unique_name:
            typ = "id"
            if default == "":
                default = None
            value = default or "ID_" + str(ArgInfo.arg_num)
        elif details.typ == str:
            typ = "str"
            value = default or name + "_STR"
        elif details.typ == int:
            typ = "int"
            if default == "":
                default = 0
            value = default or 1
        elif details.typ == bool:
            typ = "bool"
            value = default or False
        elif details.typ == float:
            typ = "float"
            value = default or 1.0
        elif "iocbuilder.modules" in str(details.typ):
            typ = "object"
            value = MagicMock(**mock_over)
        else:
            typ = "UNKNOWN TODO TODO"

        if hasattr(details, "labels") and typ != "bool":
            value = default or details.labels[0]
            typ = "enum"

        # special case because CS in pmac comes int as even though it is an int
        # TODO needs more investigation
        if name == "CS":
            typ = "int"
            value = MagicMock(**mock_over)

        if name not in self.builder_args:
            if ArgInfo.arg_num in arg_value_overrides:
                value = arg_value_overrides[ArgInfo.arg_num]
                try:
                    value = int(value)
                except (ValueError, TypeError):
                    try:
                        value = float(default)
                    except (ValueError, TypeError):
                        pass
                typ = type(value).__name__

            self.builder_args[name] = value

            if isinstance(value, MagicMock):
                value = "Object" + str(ArgInfo.arg_num)
            print(
                "    ARG {:3} {:20} {:<20} {}".format(ArgInfo.arg_num, name, value, typ)
            )

            ArgInfo.arg_num += 1

        return typ, default


class Builder2Support:
    def __init__(self, support_module_path, override_file):
        self.support_module_path = support_module_path

        self.builder_module, self.builder_classes = self._configure()
        self.dbds = set()
        self.libs = set()

        if override_file:
            if not os.path.exists(override_file):
                raise ValueError("The override file does not exist")
            with open(override_file) as f:
                # start by reading in the override file
                self.yaml_tree = YAML().load(f)
        else:
            # start with an empty YAML tree
            self.yaml_tree = CommentedMap()

    def _configure(self):
        """
        Setup the IOC builder environment and parse the support module
        """

        # Dont bother with checking for libs and object files
        device._ResourceExclusions["linux-x86_64"] = ["library", "object"]

        # ParseAndConfigure expects to be in etc/makeIocs and looks for
        # ../../configure/RELEASE relative to that
        options, _args = ParseEtcArgs(architecture="linux-x86_64")
        options.build_root = sys.argv[1] + "/etc/makeIocs"

        # this will find and load into global namespace all support modules
        # builder classes defined in **/etc/builder.py
        modules = configure.ParseAndConfigure(options, dependency_tree)

        # the last support module is the root module that we are interested in
        module = modules[-1]
        classes = self._valid_classes(module.ClassesList)

        return module, classes

    def _valid_classes(self, class_list):
        """
        Extract the list of builder classes that are relevant for conversion
        to ibek YAML.
        """
        classes = {}
        for builder_class in class_list:
            name = class_name_re.findall(str(builder_class))[0]
            if hasattr(builder_class, "ArgInfo") and not name.startswith("_"):
                classes[name] = builder_class

        return classes

    def _make_builder_object(self, name, builder_class):
        """
        Make an instance of a builder class by generating a best guess
        set of arguments to the builder class __init__ method.

        Returns:
            A tuple containing ArgInfo object that describes the arguments
            plus the instantiated builder object.
        """
        print("\nObject %s :" % builder_class.__name__)

        # Classes with a leading underscore are assumed to be private / abstract
        # builder never exposes them to xeb so we don't want them in the YAML
        if builder_class.__name__.split(".")[-1].startswith("_"):
            print("SKIPPING private class %s" % builder_class.__name__)
            return None, None

        arg_info = ArgInfo(
            name,
            getattr(builder_class, "UniqueName", "name"),
            getattr(builder_class, "__doc__"),
        )

        for a_cls in (builder_class,) + builder_class.Dependencies:
            if hasattr(a_cls, "ArgInfo"):
                arg_info.add_arg_info(a_cls.ArgInfo)
            if hasattr(a_cls, "LibFileList"):
                self.libs |= set(a_cls.LibFileList)
            if hasattr(a_cls, "DbdFileList"):
                self.dbds |= set(a_cls.DbdFileList)

        builder_object = builder_class(**arg_info.builder_args)

        return arg_info, builder_object

    def _extract_substitutions(self, arginfo):
        """
        Extract all of the database substitutions from the builder class
        and populate the ibek YAML database object graph.

        This function removes the substitutions from all_substitutions
        so must be called inside a loop that iterates over each of the
        builder classes in a module.

        Returns:
            A database object graph for the ibek YAML file, the root is an
            array of databases, since each builder class can instantiate
            multiple database templates.
        """
        all_substitutions = RecordsSubstitutionSet._SubstitutionSet__Substitutions

        databases = []

        # extract the set of templates with substitutions for the new builder object
        while all_substitutions:
            template, substitutions = all_substitutions.popitem()
            if len(substitutions[1]) > 0:
                database = CommentedMap()
                databases.append(database)
                first_substitution = substitutions[1][0]

                database["file"] = template

                print("\nDB Template %s :" % template)

                useful_args = first_substitution.Arguments[:]
                for name in DELETE_PARAMS:
                    if name in useful_args:
                        useful_args.remove(name)

                # the DB Arg entries in the YAML are Dictionary entries with no value
                print("pattern {" + ", ".join(useful_args) + "}")

                no_values = CommentedMap()
                # if the db arguments exactly match the definition parameters
                # then we can use the single regex .* to match all arguments
                if set(useful_args) == set(arginfo.all_args):
                    no_values[".*"] = None
                else:
                    print(
                        "def params don't match db_args: "
                        + str(set(arginfo.all_args) - set(useful_args))
                        + str(set(useful_args) - set(arginfo.all_args)),
                    )
                    for key in useful_args:
                        no_values[key] = None

                database.insert(3, "args", no_values)
            else:
                # this implies this is an included template - at least that is how
                # it appears with the Tetramm support module. Included templates
                # are brought in by instantiating their parent so do not need to
                # appear in the support yaml
                print(
                    "NOTE: No substitutions for %s " % template
                    + "- this should be included by the above template"
                )

        if len(databases) > 0:
            arginfo.yaml_defs["databases"] = databases

    def _make_init_script(self, builder_object, func_name, script, arginfo, when=None):
        """
        Find the source code for a builder class method and create an object
        graph representing as script entries in the ibek YAML file.
        """
        func = getattr(builder_object, func_name, None)
        if func:
            # prepare the YAML for the script entry
            script_item = CommentedMap()
            if when:
                script_item["when"] = when

            # extract the print statements from the functions in the source code
            func_text = inspect.getsource(func)
            print_strings = func_text.split("print")[1:]

            command_args = []
            warnings = False

            commands = ""
            for print_string in print_strings:
                matches = extract_multiline_print_re.findall(print_string)
                print_string = matches[0][0]
                extra = None if len(matches[0]) == 1 else matches[0][1]
                matches = extract_printed_strings_re.findall(print_string)
                if matches:
                    line = ""
                    for match in matches:
                        command_args += macros_re.findall(match[1])
                        line += macros_re.sub(macro_to_jinja_re, match[1])
                    commands += line + "\n"
                if extra is not None and extra.strip() != "":
                    warnings = True
            if commands:
                script_text = PreservedScalarString(commands)
                missing = set(command_args) - set(arginfo.all_args)
                comment = MISSING + ", ".join(missing) if missing else ""

                # remove spurious \n from the script text (not newlines)
                script_text = script_text.replace(r"\n", "")

                if warnings:
                    comment += NON_PRINT
                if comment == "":
                    comment = None
                script_item.insert(3, "value", script_text, comment=comment)

            script.append(script_item)

    def parse_initialise_functions(self, builder_object, arginfo):
        """
        Extract the code from the builder class Initialise() method
        to insert into the ibek YAML script object graph.

        Also extract the code from the builder class PostIocInitialise()
        and InitialiseOnce() methods.

        """
        pre_init = []
        post_init = []
        self._make_init_script(
            builder_object, "InitialiseOnce", pre_init, arginfo, when="first"
        )
        self._make_init_script(builder_object, "Initialise", pre_init, arginfo)
        self._make_init_script(builder_object, "PostIocInitialise", post_init, arginfo)

        if len(pre_init) > 0:
            arginfo.yaml_defs["pre_init"] = pre_init
        if len(post_init) > 0:
            arginfo.yaml_defs["post_init"] = post_init

    def start_node(self, node_path, init_val=None):
        """
        start a new node in the YAML tree, unless it already exists - this is used
        when adding any node in the tree, because the tree is initialised by an
        override file that may have already defined some of the nodes.

        args:
            node_path: the path to the node in the tree, separated by "."
            init_val: the initial value for the node
        """

        # a new CommentedMap is the typical starting value for a node
        init_val = CommentedMap() if init_val is None else init_val

        path = node_path.split(".")
        node = self.yaml_tree

        for p in path:
            if p not in node:
                node[p] = init_val
                break
            node = node[p]

    def make_yaml_tree(self):
        """
        Main entry point: generate the ibek YAML object graph from
        builder classes.
        """
        # set up the root level node of the YAML tree
        self.start_node("module", self.builder_module.Name())
        self.start_node("entity_models", [])

        for name, builder_class in self.builder_classes.items():
            # make an instance of the builder class and an ArgInfo that
            # describes all its arguments
            arginfo, builder_object = self._make_builder_object(name, builder_class)
            if builder_object is None:
                continue

            # Go and find all the arguments for all the database templates
            # and insert them plus DB file names into the YAML
            self._extract_substitutions(arginfo)

            # Extract all initialise functions and make script entries
            # for them
            self.parse_initialise_functions(builder_object, arginfo)

            self.merge_defs(arginfo.yaml_defs)

    def merge_defs(self, defn):
        """
        add a new definition to the YAML tree but merge it into the existing one
        from the overrides file if that already exists
        """

        # TODO TODO this is just an insert right now - need to merge
        self.yaml_tree["entity_models"].append(defn)

    def make_aliases(self):
        """
        Remove parameters that can be aliased to the shared anchors
        and insert aliases in place of the removed parameters.
        """

        if "shared" not in self.yaml_tree:
            return

        shared = self.yaml_tree["shared"]

        # create an index of all the shared parameters names back to their anchor
        # and also an index of all the anchor names back to their anchor
        params_index = {}
        anchors_index = {}
        anchors_alias_index = {}
        for anchor_params in shared:
            for anchor_name, anchor_params in anchor_params.items():
                for param_name, _ in anchor_params.items():
                    assert (
                        param_name not in params_index
                    ), "Duplicate parameters {} in shared".format(param_name)
                    params_index[param_name] = anchor_params
                    anchors_index[param_name] = anchor_name
                    anchors_alias_index[anchor_name] = anchor_params

        # iterate over all the defs and look for any parameters that can be aliased
        # collect the list of aliases to substitute in place of the parameters
        for defn in self.yaml_tree["entity_models"]:
            defn_params = defn["parameters"]
            aliases = []
            for param_name in defn_params.keys():
                # see if there is an anchor that has this param
                if param_name in params_index:
                    # do we already have an alias for this anchor?
                    if anchors_index[param_name] not in aliases:
                        # not yet so ...
                        # make sure this def wants all the params in the anchor
                        anchor_params = params_index[param_name]
                        if set(anchor_params.keys()).issubset(defn_params.keys()):
                            # yes - add this anchor to the list of aliases
                            aliases.append(anchors_index[param_name])
                        else:
                            # no - can't alias this parameter - go to next one
                            continue
            if aliases:
                print("def: %s, aliases: %s" % (defn["name"], aliases))
                # now delete all the aliased parameters UNLESS they have a
                # different default value to the anchor
                delete_me = []
                for alias in aliases:
                    for name, val in anchors_alias_index[alias].items():
                        anchor_default = val.get("default")
                        defn_default = defn_params[name].get("default")
                        if anchor_default == defn_default:
                            delete_me.append(name)
                for name in delete_me:
                    del defn_params[name]
                alias_str = ", ".join(["*" + a for a in aliases])
                defn_params.insert(0, "<<", alias_str)

    def write_yaml_tree(self, filename):
        """
        Convert the yaml object graph into a YAML file
        """

        def tidy_up(yaml):
            # add blank lines between major fields
            for field in [
                "  - name:",
                "    databases:",
                "    pre_init:",
                "    post_init:",
                "module",
                "entity_models",
                "      - type:",
                "      - file:",
                "      - value:",
            ]:
                yaml = re.sub(r"(\n%s)" % field, "\n\\g<1>", yaml)
            # correct aliases as the yaml write made them all strings
            yaml = re.sub(r"'<<': '(.*)'", r"<<: [\1]", yaml)
            # also correct the anchors at the top of the file
            yaml = re.sub(r"  - (.*):\n", r"  - \1: &\1\n", yaml)
            # for some reason we get unquoted 08 09 in enums - fix that
            yaml = re.sub(r"( +)(0\d*):", r"\1'\2':", yaml)
            return yaml

        yaml = YAML()

        yaml.default_flow_style = False

        # add support yaml schema
        self.yaml_tree.yaml_add_eol_comment(
            "yaml-language-server: $schema=../schemas/ibek.support.schema.json",
            column=0,
        )

        print("\nWriting YAML output to %s ..." % filename)
        with open(filename, "wb") as f:
            yaml.width = 8000  # don't do wrapping of long lines
            yaml.indent(mapping=2, sequence=4, offset=2)
            yaml.dump(self.yaml_tree, f, transform=tidy_up)


arg_override_re = re.compile(r"(\d+):(.*)")
mock_override_re = re.compile(r"(.*)\.(.*):(.*)")


def parse_override(override):
    """
    Parse the command line overrides for arguments and mock object override
    values
    """
    arg_value_match = arg_override_re.match(override)
    if arg_value_match:
        arg_num = int(arg_value_match.group(1))
        value = arg_value_match.group(2)
        arg_value_overrides[arg_num] = arg_value_match.group(2)
    else:
        arg_value_match = mock_override_re.match(override)
        if arg_value_match:
            mock_name = arg_value_match.group(1)
            prop = arg_value_match.group(2)
            value = arg_value_match.group(3)
            if mock_name not in mock_overrides:
                mock_overrides[mock_name] = {}
            mock_overrides[mock_name][prop] = value
        else:
            raise ValueError("Invalid override format: %s" % override)


def parse_args():
    """
    Parse the command line arguments
    """
    parser = argparse.ArgumentParser(
        prog="builder2ibek",
        description="A tool for converting builder.py classes to ibek support YAML",
    )
    parser.add_argument("path", help="path to the support module root folder")
    parser.add_argument("yaml", help="path to the YAML file to be generated")
    parser.add_argument(
        "overrides",
        type=parse_override,
        help=(
            "Override properties on any objects in arguments using "
            "the form 'arg_number:value'."
            "Or override a MockArg argument property in the builder class"
            "using the form 'MockArgName.property:value'. "
            "Multiple values can be passed separated by a spaces"
        ),
        nargs="*",
    )
    parser.add_argument(
        "-o", "--override", help="override file for the output YAML", default=None
    )
    args = parser.parse_args()

    return args.path, args.yaml, args.override


if __name__ == "__main__":
    (support_module_path, filename, override_file) = parse_args()

    if not os.path.exists(support_module_path):
        raise ValueError("Support module folder does not exist")
    etc_folder = support_module_path + "/etc"
    if not os.path.exists(etc_folder):
        raise ValueError("The support module path must contain an etc folder")

    builder2support = Builder2Support(support_module_path, override_file)
    # builder2support.dump_subst_file()
    builder2support.make_yaml_tree()
    # remove parameters that can be aliased to the shared anchors, insert aliases
    builder2support.make_aliases()
    if len(builder2support.yaml_tree["entity_models"]) > 0:
        builder2support.write_yaml_tree(filename)
    else:
        print("\nNo definitions - no YAML file needed for %s" % support_module_path)

    print("\nYou will require the following to make the Generic IOC Dockerfile:\n")
    print("DBD files: " + ", ".join(builder2support.dbds))
    print("LIB files: " + ", ".join(builder2support.libs))
    print("\n")
