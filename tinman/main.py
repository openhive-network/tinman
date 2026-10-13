#!/usr/bin/env python3

from importlib import import_module
import sys

class Help(object):

    @staticmethod
    def main(argv):
        print("Available commands:")
        for command_name in commands:
            print("   "+command_name)
        print("argv:", argv)
        return

commands = (
    "snapshot",
    "txgen",
    "gatling",
    "keysub",
    "sample",
    "submit",
    "warden",
    "amountsub",
    "durables",
    "prefixsub",
    "server",
    "help",
)

def main(argv):
    if len(argv) == 0:
        argv = list(argv) + ["tinman"]
    if len(argv) == 1:
        argv = list(argv) + ["--help"]
    module_name = argv[1]
    if module_name == "--help":
        module_name = "help"
    if module_name not in commands:
        print("no module specified, executing help")
        Help.main([])
        return 1
    if module_name == "help":
        module = Help
    else:
        try:
            module = import_module("." + module_name, __package__)
        except ModuleNotFoundError as error:
            if module_name == "server" and error.name in {"flask", "wtforms"}:
                print(
                    "tinman server requires optional dependencies; "
                    "install them with 'pip install tinman[server]'.",
                    file=sys.stderr,
                )
                return 2
            raise
    return module.main(argv[1:])

def sys_main():
    result = main(sys.argv)
    if result is None:
        result = 0
    sys.exit(result)

if __name__ == "__main__":
    sys_main()
