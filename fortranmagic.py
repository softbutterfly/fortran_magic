# -*- coding: utf-8 -*-
"""
=====================
Fortran 90/f2py magic
=====================

{FORTRAN_DOC}



Author:
* Martín Gaitán <gaitan@gmail.com>

This code was heavily inspired in the Cython magic
"""

from __future__ import print_function

import imp
import io
import os
import sys

try:
    import hashlib
except ImportError:
    import md5 as hashlib

from IPython.core.error import UsageError
from IPython.core.magic import Magics, magics_class, line_magic, cell_magic
from IPython.core import display, magic_arguments
from IPython.utils import py3compat
from IPython.utils.io import capture_output
from IPython.utils.path import get_ipython_cache_dir
from numpy.f2py import f2py2e
from numpy.distutils import fcompiler
from distutils.core import Distribution
from distutils.ccompiler import compiler_class
from distutils.command.build_ext import build_ext

fcompiler.load_all_fcompiler_classes()

@magics_class
class FortranMagics(Magics):


    allowed_fcompilers = sorted(fcompiler.fcompiler_class.keys())
    allowed_compilers = sorted(compiler_class.keys())

    def __init__(self, shell):
        super(FortranMagics, self).__init__(shell)
        self._reloads = {}
        self._code_cache = {}
        self._lib_dir = os.path.join(get_ipython_cache_dir(), 'fortran')
        if not os.path.exists(self._lib_dir):
            os.makedirs(self._lib_dir)

    def _import_all(self, module):
        for k, v in module.__dict__.items():
            if not k.startswith('__'):
                self.shell.push({k: v})

    def _run_f2py(self, argv, show_captured=False):
        """
        Here we directly call the numpy.f2py.f2py2e.run_compile() entry point,
        after some small amount of setup to get sys.argv and the current
        working directory set appropriately.
        """
        old_argv = sys.argv
        old_cwd = os.getcwdu() if sys.version_info[0] == 2 else os.getcwd()
        try:
            sys.argv = ['f2py'] + list(map(str, argv))
            os.chdir(self._lib_dir)
            try:
                with capture_output() as captured:
                    f2py2e.main()
                if show_captured:
                    captured()
            except SystemExit as e:
                captured()
                raise UsageError(str(e))
        finally:
            sys.argv = old_argv
            os.chdir(old_cwd)

    @magic_arguments.magic_arguments()
    @magic_arguments.argument(
        '--help-link', default='all', required=False,
        help="""List system resources found by system_info.py.
                Optionally give a resource name.
                E.g. try '--help-link lapack_opt.

                See alsof
                %%fortran --link <resource> switch.
                """
    )
    @magic_arguments.argument(
        '--help-fcompiler', action="store_true",
        help="List available Fortran compilers",
    )
    @magic_arguments.argument(
        '--help-compiler', action="store_true",
        help="List available C compilers",
    )
    @line_magic
    def f2py(self, line):
        args = magic_arguments.parse_argstring(self.f2py, line)
        if args.help_fcompiler:
            self._run_f2py(['-c', '--help-fcompiler'], True)
        elif args.help_compiler:
            self._run_f2py(['-c', '--help-compiler'], True)
        elif len(args.help_link) == 0:
            self._run_f2py(['--help-link'])
        elif len(args.help_link) > 0:
            self._run_f2py(['--help-link', args.help_link], True)

    @magic_arguments.magic_arguments()
    @magic_arguments.argument(
        '--fcompiler',
        choices=allowed_fcompilers,
        help="""Specify Fortran compiler type by vendor.
                See %%f2py --help-fcompiler to list available on your platform""",
    )
    @magic_arguments.argument(
        '--compiler',
        choices=allowed_compilers,
        help="""Specify C compiler type (as defined by distutils).
                See %%f2py --help-compiler"""
    )
    @magic_arguments.argument(
        '--f90flags', help="Specify F90 compiler flags"
    )
    @magic_arguments.argument(
        '--f77flags', help="Specify F77 compiler flags"
    )
    @magic_arguments.argument(
        '--opt', help="Specify optimization flags"
    )
    @magic_arguments.argument(
        '--arch', help="Specify architecture specific optimization flags"
    )
    @magic_arguments.argument(
        '--noopt', action="store_true", help="Compile without optimization"
    )
    @magic_arguments.argument(
        '--noarch', action="store_true", help="Compile without arch-dependent optimization"
    )
    @magic_arguments.argument(
        '--debug', action="store_true", help="Compile with debugging information"
    )
    @magic_arguments.argument(
        '--link',
           help="""Link extension module with <resources> as defined
                   by numpy.distutils/system_info.py. E.g. to link
                   with optimized LAPACK libraries (vecLib on MacOSX,
                   ATLAS elsewhere), use --link lapack_opt.
                   See also --help-link switch."""
    )
    @cell_magic
    def fortran(self, line, cell):
        """Compile and import everything from a Fortran code cell, using f2py.

        The contents of the cell are written to a `.f90` file in the
        directory `IPYTHONDIR/fortran` using a filename with the hash of the
        code. This file is then compiled. The resulting module
        is imported and all of its symbols are injected into the user's
        namespace.


        Usage
        =====
        Prepend ``%%fortran`` to your fortran code in a cell::

        ``%%fortran

        ! put your code here.
        ``


        """
        args = magic_arguments.parse_argstring(self.fortran, line)

        # boolean flags
        f2py_args = ['--%s' % k for k, v in vars(args).items() if v is True]

        if args.link:
            print(args.link)

        kw = ['--%s=%s' % (k, v) for k, v in vars(args).items()
                          if isinstance(v, basestring)]

        f2py_args.extend(kw)
        code = cell if cell.endswith('\n') else cell+'\n'
        key = code, sys.version_info, sys.executable, f2py2e.f2py_version

        module_name = "_fortran_magic_" + \
                      hashlib.md5(str(key).encode('utf-8')).hexdigest()

        module_path = os.path.join(self._lib_dir, module_name + self.so_ext)

        f90_file = os.path.join(self._lib_dir, module_name + '.f90')
        f90_file = py3compat.cast_bytes_py2(f90_file,
                                            encoding=sys.getfilesystemencoding())
        with io.open(f90_file, 'w', encoding='utf-8') as f:
            f.write(code)

        self._run_f2py(f2py_args + ['-m', module_name, '-c', f90_file])

        self._code_cache[key] = module_name
        module = imp.load_dynamic(module_name, module_path)
        self._import_all(module)

    @property
    def so_ext(self):
        """The extension suffix for compiled modules."""
        try:
            return self._so_ext
        except AttributeError:

            dist = Distribution()
            config_files = dist.find_config_files()
            try:
                config_files.remove('setup.cfg')
            except ValueError:
                pass
            dist.parse_config_files(config_files)
            build_extension = build_ext(dist)
            build_extension.finalize_options()
            self._so_ext = build_extension.get_ext_filename('')
            return self._so_ext

# __doc__ = __doc__.format(FORTRAN_DOC=' ' * 8 + FortranMagics.fortran.__doc__)


def load_ipython_extension(ip):
    """Load the extension in IPython."""
    ip.register_magics(FortranMagics)

    # enable fortran highlight
    patch = ("IPython.config.cell_magic_highlight['magic_fortran'] = {'reg':[/^%%fortran/]};")
    js = display.Javascript(data=patch,
                            lib=["https://raw.github.com/marijnh/CodeMirror/master/mode/fortran/fortran.js"])
    display.display_javascript(js)
