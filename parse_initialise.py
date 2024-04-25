"""
Given the source code of a builder.py Initialize function, use AST to
extract all the print statements and convert them into Jinja template text.
"""

import ast


def parse_intialise(source):
    func_text = inspect.getsource(func)
    # fix up the indenting by adding the enclosing class
    func_text = "class Dummy:\n" + func_text
    # get an abstract syntax tree of the function body
    code = ast.parse(func_text)

    # walk the code of Initialise function
    for node in code.body[0].body[0].body:
        if isinstance(node, _ast.Print):
            print("PRINT: ", node.values)
        else:
            print("non-PRINT line", node.lineno)


    return "test", [23,22]
