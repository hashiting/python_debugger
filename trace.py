import sys
import inspect

def remove_html_markup(s):
    tag = False
    quote = False
    out = ""

    for c in s:
        assert tag or not quote

        if c == '<' and not quote:
            tag = True
        elif c == '>' and not quote:
            tag = False
        elif (c == '"' or c == "'") and tag:
            quote = not quote
        elif not tag:
            out = out + c

    return out

class Tracer(object):
    def __init__(self, file=sys.stdout):
        """Trace a block of code, sending logs to file (default: stdout)"""
        self.original_trace_function = None
        self.file = file
        pass

    def log(self, *objects, sep=' ', end='\n', flush=False):
        """Like print(), but always sending to file given at initialization,
           and always flushing"""
        print(*objects, sep=sep, end=end, file=self.file, flush=True)

    def traceit(self, frame, event, arg):
        """Tracing function. To be overridden in subclasses."""
        self.log(event, frame.f_lineno, frame.f_code.co_name, frame.f_locals)

    def _traceit(self, frame, event, arg):
        """Internal tracing function."""
        if frame.f_code.co_name == '__exit__':
            # Do not trace our own __exit__() method
            pass
        else:
            self.traceit(frame, event, arg)
        return self._traceit

    def __enter__(self):
        """Called at begin of `with` block. Turn tracing on."""
        self.original_trace_function = sys.gettrace()
        sys.settrace(self._traceit)

    def __exit__(self, tp, value, traceback):
        """Called at begin of `with` block. Turn tracing off."""
        sys.settrace(self.original_trace_function)

class Tracer(Tracer):
    def traceit(self, frame, event, arg):
        if event == 'line':
            module = inspect.getmodule(frame.f_code)
            if module is None:
                source = inspect.getsource(frame.f_code)
            else:
                source = inspect.getsource(module)
            current_line = source.split('\n')[frame.f_lineno - 1]
            self.log(frame.f_lineno, current_line)

class Variable_Tracer(Tracer):
    def __init__(self, file=sys.stdout):
        self.last_vars = {}
        super().__init__(file=file)

    def changed_vars(self, new_vars):
        changed = {}
        for var_name in new_vars:
            if (var_name not in self.last_vars or
                    self.last_vars[var_name] != new_vars[var_name]):
                changed[var_name] = new_vars[var_name]
        self.last_vars = new_vars.copy()
        return changed
    def print_debugger_status(self, frame, event, arg):
        changes = self.changed_vars(frame.f_locals)
        changes_s = ", ".join([var + " = " + repr(changes[var])
                               for var in changes])

        if event == 'call':
            self.log("Calling " + frame.f_code.co_name + '(' + changes_s + ')')
        elif changes:
            self.log(' ' * 40, '#', changes_s)

        if event == 'line':
            module = inspect.getmodule(frame.f_code)
            if module is None:
                source = inspect.getsource(frame.f_code)
            else:
                source = inspect.getsource(module)
            current_line = source.split('\n')[frame.f_lineno - 1]
            self.log(repr(frame.f_lineno) + ' ' + current_line)

        if event == 'return':
            self.log(frame.f_code.co_name + '()' + " returns " + repr(arg))
            self.last_vars = {}  # Delete 'last' variables

    def traceit(self, frame, event, arg):
        self.print_debugger_status(frame, event, arg)

# with Variable_Tracer():
#     remove_html_markup("abc")
# print("\n")
class ConditionalTracer(Variable_Tracer):
    def __init__(self, file=sys.stdout, condition=None):
        if condition is None:
            condition = "False"
        self.condition = condition
        self.last_report = None
        super().__init__(file=file)
    def eval_in_context(self, expr, frame):
        try:
            cond = eval(expr, None, frame.f_locals)
        except NameError:  # (yet) undefined variable
            cond = None
        return cond
    def do_report(self, frame, event, arg):
        return self.eval_in_context(self.condition, frame)
    def traceit(self, frame, event, arg):
        report = self.do_report(frame, event, arg)
        if report != self.last_report:
            if report:
                self.log("...")
            self.last_report = report

        if report:
            self.print_debugger_status(frame, event, arg)

# with ConditionalTracer(condition='quote'):
#     remove_html_markup('<b title="bar">"foo"</b>')

class Debugger(Variable_Tracer):
    """Interactive Debugger"""

    def __init__(self, file=sys.stdout):
        """Create a new interactive debugger."""
        self.stepping = True
        self.breakpoints = set()
        self.interact = True

        self.frame = None
        self.event = None
        self.arg = None

        super().__init__(file)
    def traceit(self, frame, event, arg):
        """Tracing function; called at every line"""
        self.frame = frame
        self.event = event
        self.arg = arg

        if self.stop_here():
            self.interaction_loop()

        return self.traceit
    def stop_here(self):
        """Return true if we should stop"""
        return self.stepping or self.frame.f_lineno in self.breakpoints
    def interaction_loop(self):
        """Interact with the user"""
        self.print_debugger_status(self.frame, self.event, self.arg)

        self.interact = True
        while self.interact:
            command = input("(debugger) ")
            self.execute(command)
    def step_command(self, arg=""):
        """Execute up to the next line"""
        self.stepping = True
        self.interact = False
    def continue_command(self, arg=""):
        """Resume execution"""
        self.stepping = False
        self.interact = False
    def execute(self, command):
        sep = command.find(' ')
        if sep > 0:
            cmd = command[:sep].strip()
            arg = command[sep + 1:].strip()
        else:
            cmd = command.strip()
            arg = ""

        method = self.command_method(cmd)
        if method:
            method(arg)
    def help_command(self, command=""):
        """Give help on given command. If no command is given, give help on all"""

        if command:
            possible_cmds = [possible_cmd for possible_cmd in self.commands()
                             if possible_cmd.startswith(command)]

            if len(possible_cmds) == 0:
                self.log(f"Unknown command {repr(command)}. Possible commands are:")
                possible_cmds = self.commands()
            elif len(possible_cmds) > 1:
                self.log(f"Ambiguous command {repr(command)}. Possible expansions are:")
        else:
            possible_cmds = self.commands()

        for cmd in possible_cmds:
            method = self.command_method(cmd)
            self.log(f"{cmd:10} -- {method.__doc__}")

    def print_command(self, arg=""):
        """Print an expression. If no expression is given, print all variables"""
        vars = self.frame.f_locals

        if not arg:
            self.log("\n".join([f"{var} = {repr(vars[var])}" for var in vars]))
        else:
            try:
                self.log(f"{arg} = {repr(eval(arg, globals(), vars))}")
            except Exception as err:
                self.log(f"{err.__class__.__name__}: {err}")
    def list_command(self, arg=""):
        """Show current function."""
        source_lines, line_number = inspect.getsourcelines(self.frame.f_code)

        for line in source_lines:
            self.log(f'{line_number:4} {line}', end='')
            line_number += 1
    def break_command(self, arg=""):
        """Set a breakoint in given line. If no line is given, list all breakpoints"""
        if arg:
            self.breakpoints.add(int(arg))
        self.log("Breakpoints:", self.breakpoints)
    def delete_command(self, arg=""):
        """Delete breakoint in given line. Without given line, clear all breakpoints"""
        if arg:
            try:
                self.breakpoints.remove(int(arg))
            except KeyError:
                self.log(f"No such breakpoint: {arg}")
        else:
            self.breakpoints = set()
        self.log("Breakpoints:", self.breakpoints)
    def commands(self):
        cmds = [method.replace('_command', '')
                for method in dir(self.__class__)
                if method.endswith('_command')]
        cmds.sort()
        return cmds
    def command_method(self, command):
        if command.startswith('#'):
            return None  # Comment

        possible_cmds = [possible_cmd for possible_cmd in self.commands()
                         if possible_cmd.startswith(command)]
        if len(possible_cmds) != 1:
            self.help_command(command)
            return None

        cmd = possible_cmds[0]
        return getattr(self, cmd + '_command')
    def list_command(self, arg=""):
        """Show current function. If arg is given, show its source code."""
        if arg:
            try:
                obj = eval(arg)
                source_lines, line_number = inspect.getsourcelines(obj)
            except Exception as err:
                self.log(f"{err.__class__.__name__}: {err}")
                return
            current_line = -1
        else:
            source_lines, line_number = \
                inspect.getsourcelines(self.frame.f_code)
            current_line = self.frame.f_lineno

        for line in source_lines:
            spacer = ' '
            if line_number == current_line:
                spacer = '>'
            elif line_number in self.breakpoints:
                spacer = '#'
            self.log(f'{line_number:4}{spacer} {line}', end='')
            line_number += 1
    def quit_command(self, arg=""):
        """Finish execution"""
        self.breakpoints = []
        self.stepping = False
        self.interact = False
    
    
    

with Debugger():
    remove_html_markup('abc')
    