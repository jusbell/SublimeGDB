import sublime
import sublime_plugin
import subprocess
import threading
import time
import traceback
import sys
import os
import re

breakpoints = {}

gdb_breakpoints = []
#

class GDBBreakpoint:
    def __init__(self, string):
        print "Breakpoint"
        string = string.split(",")
        self.data = {}
        for pair in string:
            key, value = pair.split("=")
            value = value.replace("\"", "")
            print "key: %s, value: %s" % (key, value)
            self.data[key] = value

def extract_breakpoints(line):
    global gdb_breakpoints
    gdb_breakpoints = []
    bps = re.findall("(?<=,bkpt\=\{)[a-zA-Z,=/\"0-9.]+", line)
    for bp in bps:
        gdb_breakpoints.append(GDBBreakpoint(bp))


def update(view):
    bps = []
    for line in breakpoints[view.file_name()]:
        bps.append(view.full_line(view.text_point(line - 1, 0)))
    view.add_regions("sublimegdb.breakpoints", bps, "keyword.gdb", "circle", sublime.HIDDEN)
    #if hit_breakpoint:

    # cursor: view.add_regions("sublimegdb.position", breakpoints[view.file_name()], "entity.name.class", "bookmark", sublime.HIDDEN)

def run_cmd(cmd, block=False):
    global is_at_prompt
    is_at_prompt = False
    gdb_process.stdin.write("%s\n" % cmd)
    while block and not is_at_prompt:
        time.sleep(0.1)

def add_breakpoint(filename, line):
    breakpoints[filename].append(line)
    start_at_prompt = is_at_prompt
    if is_running():
        if not is_at_prompt:
            run_cmd("-exec-interrupt", True)
        run_cmd("-break-insert %s:%d" % (filename, line))
        if not start_at_prompt:
            run_cmd("-exec-continue")


def remove_breakpoint(filename, line):
    breakpoints[filename].remove(line)
    start_at_prompt = is_at_prompt
    if is_running():
        while not is_at_prompt:
            run_cmd("-exec-interrupt")
            time.sleep(0.1)
        run_cmd("-break-list", True)
        for bp in gdb_breakpoints:
            if bp.data["file"] == filename and bp.data["line"] == str(line):
                print "found!"
                run_cmd("-break-delete %s" % bp.data["number"])
                break

        if not start_at_prompt:
            run_cmd("-exec-continue")

def toggle_breakpoint(filename, line):
    if line in breakpoints[filename]:
        remove_breakpoint(filename, line)
    else:
        add_breakpoint(filename, line)

def sync_breakpoints():
    for file in breakpoints:
        for bp in breakpoints[file]:
            cmd = "-break-insert %s:%d" % (file, bp)
            run_cmd(cmd)



class GdbToggleBreakpoint(sublime_plugin.TextCommand):
    def run(self, edit):
        fn = self.view.file_name()
        if fn not in breakpoints:
            breakpoints[fn] = []

        line, col = self.view.rowcol(self.view.sel()[0].a)
        toggle_breakpoint(fn, line + 1)
        update(self.view)

is_at_prompt = False

gdb_process = None
lock = threading.Lock()
output = []

def get_view():
    gdb_view = sublime.active_window().open_file("GDB Session")
    gdb_view.set_scratch(True)
    gdb_view.set_read_only(True)
    return gdb_view

def update_view():
    global output
    lock.acquire()
    try:
        gdb_view = get_view()
        if (gdb_view.is_loading()):
            sublime.set_timeout(update_view, 100)
            return

        e = gdb_view.begin_edit()
        try:
            gdb_view.set_read_only(False)
            for line in output:
                gdb_view.insert(e, gdb_view.size(), line)
            gdb_view.set_read_only(True)
            gdb_view.show(gdb_view.size())
            output = []
        finally:
            gdb_view.end_edit(e)
    finally:
        lock.release()



def gdboutput(pipe):
    global gdb_process
    global old_stdin
    global lock
    global output
    global is_at_prompt
    while True:
        try:
            if gdb_process.poll() != None:
                break
            line = pipe.readline().strip()
            is_at_prompt = "(gdb)" in line

            if len(line) > 0:
                if "BreakpointTable" in line:
                    extract_breakpoints(line)
                lock.acquire()
                output.append("%s\n" % line)
                lock.release()
                sublime.set_timeout(update_view, 0)
        except:
            traceback.print_exc()
    if pipe == gdb_process.stdout:
        lock.acquire()
        output.append("GDB session ended\n")
        lock.release()
        sublime.set_timeout(update_view, 0)


def show_input():
    sublime.active_window().show_input_panel("GDB", "", input_on_done, input_on_change, input_on_cancel)

class GdbInput(sublime_plugin.TextCommand):
    def run(self, edit):
        show_input()


def input_on_done(s):
    gdb_process.stdin.write("%s\n" % s)
    if s.strip() != "quit":
        show_input()

def input_on_cancel():
    pass

def input_on_change(s):
    pass


def get_setting(key, default=None):
    try:
        s = sublime.active_window().active_view().settings()
        if s.has("sublimegdb_%s" % key):
            return s.get("sublimegdb_%s" % key)
    except:
        pass
    return sublime.load_settings("SublimeGDB.sublime-settings").get(key, default)


def is_running():
    return gdb_process != None and gdb_process.poll() == None


class GdbLaunch(sublime_plugin.TextCommand):
    def run(self, edit):
        global gdb_process
        if gdb_process == None or gdb_process.poll() != None:
            os.chdir(get_setting("workingdir", "/tmp"))
            commandline = get_setting("commandline")
            commandline.insert(1, "--interpreter=mi")
            gdb_process = subprocess.Popen(commandline, shell=False, stdin=subprocess.PIPE, stdout=subprocess.PIPE)
            sync_breakpoints()
            gdb_process.stdin.write("-exec-run\n")

            t = threading.Thread(target=gdboutput, args=(gdb_process.stdout,))
            t.start()

            show_input()
        else:
            sublime.status_message("GDB is already running!")

class GdbEventListener(sublime_plugin.EventListener):
    def on_query_context(self, view, key, operator, operand, match_all):
        global gdb_process
        if key != "gdb_running":
            return None
        return is_running() == operand




