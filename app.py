#!/usr/bin/env python
import sys, os, bottle
os.chdir(os.path.dirname(os.path.abspath(__file__)))
from bottle import route, run, default_app, debug, template, request, get, post, jinja2_view, static_file
import tempfile
import subprocess
from csim import Nios2
import json
import copy
import numpy as np
import gc


app = application = default_app()



def nios2_as(asm):
    asm_f = tempfile.NamedTemporaryFile()
    asm_f.write(asm)
    asm_f.flush()

    obj_f = tempfile.NamedTemporaryFile()

    ########## Assemble
    p = subprocess.Popen(['bin/nios2-elf-as', \
                          asm_f.name, \
                          '-o', obj_f.name],
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if p.wait() != 0:
        ret = 'Assembler error: %s' % p.stderr.read()
        obj_f.close()
        asm_f.close()
        p.stdout.close()
        p.stderr.close()
        return ret

    asm_f.close()
    p.stdout.close()
    p.stderr.close()


    ######### Link
    exe_f = tempfile.NamedTemporaryFile()
    p = subprocess.Popen(['bin/nios2-elf-ld', \
                          '-T', 'de10.ld', \
                          obj_f.name, '-o', exe_f.name],
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE) 
    if p.wait() != 0:
        ret = 'Linker error: %s' % p.stderr.read()
        p.stderr.close()
        p.stdout.close()
        obj_f.close()
        return ret

    obj_f.close()
    p.stdout.close()
    p.stderr.close()

    ######## objdump
    p = subprocess.Popen(['./gethex.sh', exe_f.name], \
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if p.wait() != 0:
        ret = 'Objdump error: %s' % p.stderr.read()
        p.stderr.close()
        p.stdout.close()
        exe_f.close()
        return ret

    obj = json.loads(p.stdout.read().decode('ascii'))
    p.stdout.close()
    p.stderr.close()
    exe_f.close()

    return obj


@post('/nios2/as')
@jinja2_view('as.html')
def post_as():
    asm = request.forms.get("asm")
    obj = nios2_as(asm.encode('utf-8'))

    if not(isinstance(obj, dict)):
        return {'prog': 'Error: %s' % obj,
                'success': False,
                'code': asm}

    return {'prog': json.dumps(obj),
            'success': True,
            'code': asm}


@get('/nios2/as')
@jinja2_view('as.html')
def get_as():
    return {}

def require_symbols(obj, symbols):
    for s in symbols:
        if s not in obj['symbols']:
            return '%s not found in memory (did you enter any instructions?)' % (s)
    return None

# Returns (correct_bool, feedback)
def check_find_min(obj):
    r = require_symbols(obj, ['MIN', 'ARR'])
    if r is not None:
        return (False, r)

    feedback = ''

    test_cases = [
        ([5, 3, 9, 2], 2),
        ([5, -8, 1, 12, 6], -8),
        ]

    cpu = Nios2(obj=obj)

    cur_test = 1
    for arr, ans in test_cases:

        # Reset and initialize
        cpu.reset()
        for i, val in enumerate(arr):
            cpu.write_symbol_word('ARR', np.uint32(val), offset=i*4)
        cpu.write_symbol_word('N', len(arr))

        # Run
        instrs = cpu.run_until_halted(10000)

        # Check answer
        their_ans = np.int32(cpu.get_symbol_word('MIN'))
        if their_ans != ans:
            feedback += 'Failed test case %d: ' % (cur_test)
            feedback += 'MIN should be %d (0x%08x) for ARR %s. ' % (ans, np.uint32(ans), arr)
            feedback += 'Your code produced MIN=0x%08x' % np.uint32(their_ans)
            feedback += '<br/><br/>Memory:<br/><pre>'
            feedback += cpu.dump_mem(0, 0x100)
            feedback += '\nSymbols:\n' + cpu.dump_symbols()
            feedback += '</pre>'

            return (False, feedback)

        feedback += 'Passed test case %d<br/>\n' % (cur_test)
        cur_test += 1

    return (True, feedback)

def check_array_sum(obj):
    r = require_symbols(obj, ['SUM', 'ARR'])
    if r is not None:
        return (False, r)

    test_cases = [
        ([5, 3, 9, 2], 19),
        ([5, -8, 1, 12, 6], 24),
        ([1, -8, -1, 0, 1, 1], 3),
        ]

    cpu = Nios2(obj=obj)

    cur_test = 1
    for arr, ans in test_cases:

        # Reset and initialize
        cpu.reset()
        for i, val in enumerate(arr):
            cpu.write_symbol_word('ARR', np.uint32(val), offset=i*4)
        cpu.write_symbol_word('N', len(arr))

        # Run
        instrs = cpu.run_until_halted(10000)

        # Check answer
        their_ans = np.uint32(cpu.get_symbol_word('SUM'))
        if their_ans != ans:
            feedback += 'Failed test case %d: ' % (cur_test)
            feedback += 'SUM should be %d (0x%08x) for ARR %s. ' % (ans, np.uint32(ans), arr)
            feedback += 'Your code produced SUM=0x%08x' % np.uint32(their_ans)
            feedback += '<br/><br/>Memory:<br/><pre>'
            feedback += cpu.dump_mem(0, 0x100)
            feedback += '\nSymbols:\n' + cpu.dump_symbols()
            feedback += '</pre>'

            return (False, feedback)

        feedback += 'Passed test case %d<br/>\n' % (cur_test)
        cur_test += 1

    return (True, feedback)



def get_debug(cpu, mem_len=0x100, show_stack=False):
    out = '<br/>\n'
    err = cpu.get_error()
    if err != None:
        out += err
    out += '<br/>Memory:<br/><pre>'
    out += cpu.dump_mem(0, mem_len)
    out += '\nSymbols:\n' + cpu.dump_symbols()
    out += '</pre>'
    if show_stack:
        sp = cpu.get_reg(27)
        fp = cpu.get_reg(28)
        out += '<br/>Stack:<br/><pre>'
        out += 'sp = 0x%08x\nfp = 0x%08x\n\n' % (sp, fp)
        diff = 0x04000000 - (sp-0x80)
        out += cpu.dump_mem(sp-0x80, min(0x100, diff))
        out += '\n</pre>'
    return out



def check_led_on(obj):
    cpu = Nios2(obj=obj)


    # Make a MMIO rw/register
    leds = Nios2.MMIO_Reg()
    # Set the cpu's LED MMIO callback to that reg's access function
    cpu.add_mmio(0xFF200000, leds.access)
    #cpu.mmios[0xFF200000] = leds.access

    instrs = cpu.run_until_halted(1000000)

    feedback = ''
    if (leds.load() & 0x3ff) != 0x3ff:
        feedback += 'Failed test case 1: '
        feedback += 'LEDs are set to %s (should be %s)' % (bin(leds.load()&0x3ff), bin(0x3ff))
        feedback += get_debug(cpu)
        del cpu
        return (False, feedback)

    del cpu
    return (True, 'Passed test case 1')


def check_proj1(obj):
    cpu = Nios2(obj=obj)

    class p1grader(object):
        def __init__(self, test_cases=[]):
            # Array of (sw_val, expected_led_val)
            self.test_cases = test_cases
            self.cur_test = 0
            self.feedback = ''
            self.num_passed = 0

        def write_led(self, val):
            # Assert correct answer
            sw, expected = self.test_cases[self.cur_test]
            if val != expected: # Check that they wrote to LEDs exactly
                if (val&0x3ff) != expected: # only warn if the LEDs would have masked for them..

                    self.feedback += 'Failed test case %d: ' % (self.cur_test+1)
                    self.feedback += 'LEDs set to %s (should be %s) for SW %s' % \
                                (bin(val&0x3ff), bin(expected), bin(sw))
                    self.feedback += get_debug(cpu)
                    cpu.halt()
                    return
                self.feedback += 'Test case %d: ' %(self.cur_test+1)
                self.feedback += 'Warning: wrote 0x%08x (instead of 0x%08x) to LEDs for SW %s;' %\
                                (val, expected, bin(sw))
                self.feedback += ' upper bits ignored.\n'
            self.feedback += 'Passed test case %d<br/>\n' % (self.cur_test+1)
            self.cur_test += 1
            self.num_passed += 1
            if self.cur_test >= len(self.test_cases):
                cpu.halt()

        def read_sw(self):
            if self.cur_test > len(self.test_cases):
                print('Error: read_sw after we should have halted?')
                return 0    # ??
            sw, led = self.test_cases[self.cur_test]
            return sw

    tests = [(0, 0),
            (0b0000100001, 2),
            (0b0001100010, 5),
            (0b1011101110, 37),
            (0b1111111111, 62),
            (0b1111011111, 61),
            (0b0000111111, 32)]

    p1 = p1grader(tests)

    cpu.add_mmio(0xFF200000, p1.write_led)
    cpu.add_mmio(0xFF200040, p1.read_sw)

    #cpu.mmios[0xFF200000] = p1.write_led
    #cpu.mmios[0xFF200040] = p1.read_sw

    instrs = cpu.run_until_halted(10000)

    print('Passed %d of %d' % (p1.num_passed, len(tests)))
    err = cpu.get_error()
    if err is None:
        err = ''
    del cpu
    return (p1.num_passed==len(tests), err + p1.feedback)

def check_list_sum(obj):
    r = require_symbols(obj, ['SUM', 'HEAD'])
    if r is not None:
        return (False, r)

    cpu = Nios2(obj=obj)


    tests = [([3, 2, 1], 6),
             ([1, 0, 4], 5),
             ([-1, 2, 15, 8, 6], 30)]

    head_addr = obj['symbols']['HEAD']

    feedback = ''

    cur_test = 1
    for tc,ans in tests:
        cpu.reset()
        for ii,n in enumerate(tc):

            next_ptr = head_addr + (ii+1)*8
            if ii == len(tc)-1:
                # Last element, write null for pointer
                next_ptr = 0
            cpu.storeword(head_addr+ii*8, next_ptr)
            cpu.storeword(head_addr+ii*8+4, np.uint32(n))

        instrs = cpu.run_until_halted(1000000)

        their_ans = np.int32(cpu.get_symbol_word('SUM'))
        if their_ans != ans:
            feedback += 'Failed test case %d: ' % cur_test
            feedback += 'SUM was %d (0x%08x), should be %d (0x%08x)' % \
                    (their_ans, np.uint32(their_ans), ans, np.uint32(ans))
            feedback += get_debug(cpu)
            del cpu
            return (False, feedback)

        feedback += 'Passed test case %d<br/>\n' % cur_test

        cur_test += 1

    del cpu
    return (True, feedback)

def check_fib(obj):
    r = require_symbols(obj, ['N', 'F'])
    if r is not None:
        return (False, r)

    cpu = Nios2(obj=obj)

    tests = [(10, 55), (15, 610), (12, 144), (30, 832040)]
    feedback = ''
    cur_test = 1
    for n,ans in tests:
        cpu.reset()
        cpu.write_symbol_word('N', n)

        instrs = cpu.run_until_halted(100000000)

        their_ans = cpu.get_symbol_word('F')
        if their_ans != ans:
            feedback += 'Failed test case %d: ' % cur_test
            feedback += 'fib(%d) returned %d, should have returned %d' %\
                    (n, their_ans, ans)
            feedback += get_debug(cpu, show_stack=True)
            del cpu
            return (False, feedback)
        feedback += 'Passed test case %d<br/>\n' % cur_test
        cur_test += 1

    del cpu
    return (True, feedback)


def check_sort(obj):
    r = require_symbols(obj, ['N', 'SORT'])
    if r is not None:
        return (False, r)

    cpu = Nios2(obj=obj)

    tests = [[5, 4, 3, 2, 1],
             [5, 4, 2, 3, 1],
             [2, 8, 3, 9, 15, 10],
             [8, -1, 11, 14, 12, 14, 0],
             [9, -2, 5, 0, -2, 0, -1, -4, 1, 9, 10, 6, -3, 7, 5, 10, 9, -2, 2, 9, 0, 3, -3, 7, 7, 6, -5, -2, -1, -4]]
    feedback = ''
    cur_test = 1
    tot_instr = 0
    for tc in tests:
        cpu.reset()
        ans = sorted(tc)
        cpu.write_symbol_word('N', len(tc))
        for i,t in enumerate(tc):
            cpu.write_symbol_word('SORT', t, offset=i*4)

        instrs = cpu.run_until_halted(100000000)
        tot_instr += instrs

        # Read back out SORT
        their_ans = [np.int32(cpu.get_symbol_word('SORT', offset=i*4)) for i in range(len(tc))]

        if their_ans != ans:
            feedback += 'Failed test case %d: ' % cur_test
            feedback += 'Sorting %s<br/>\n' % tc
            feedback += 'Code provided: %s<br/>\n' % their_ans
            feedback += 'Correct answer: %s<br/>\n' % ans
            feedback += get_debug(cpu)
            del cpu
            return (False, feedback, None)
        feedback += 'Passed test case %d<br/>\n' % cur_test
        cur_test += 1
    del cpu
    extra_info = '%d total instructions' % tot_instr
    return (True, feedback, extra_info)




exercises = {
    ###############
    # Find Minimum
    'find-min': {
        'public': True,
        'diff': 'easy',
        'title': 'Find the minimum value in an array',
        'desc': '''You are given an array of words starting at <code>ARR</code>,
                    that contains <code>N</code> words in it.<br/>
                    <br/>
                    Your task is to write code to find the <b>lowest</b> signed value in the
                    array. Write the value to the word <code>MIN</code> in memory, and then
                    call the <code>break</code> instruction.''',
        'code': '''.text
_start:

.data
# Make sure ARR is the last label in .data
MIN: .word 0
N:   .word 5
ARR: .word 5, -8, -1, 12, 6
''',
        'checker': check_find_min
    },
    ##############
    # Sum the array
    'sum-array': {
        'public': True,
        'title': 'Array Sum',
        'diff':  'easy',
        'desc': '''You are given an array of signed words starting at <code>ARR</code> for length <code>N</code> words.
                   <br/><br/>
                   Find the sum of all the <b>positive</b> integers, and write the value to the word
                   <code>SUM</code> in memory, then call the <code>break</code> instruction.''',
        'code':'''.text
_start:

.data
# Make sure ARR is the last label in .data
SUM: .word 0
N:   .word 6
ARR: .word 14, 22, 0, -9, -12, 27
''',
        'checker': check_array_sum
    },
    ##########
    # Set the LEDs to all on
    'led-on': {
        'public': True,
        'title': 'Set LEDs on',
        'diff':  'easy',
        'desc': '''Turn on all 10 LEDs on the DE10-Lite, then call the <code>break</code> instruction.<br/><br/>
                    Hint: the LED MMIO address is <code>0xFF200000</code>''',
        'code':'''.text
_start:
''',
        'checker': check_led_on
    },
    ###########
    # Project 1
    'proj1': {
        'public': True,
        'title': 'Project 1',
        'diff': 'medium',
        'desc': '''Project 1 adder.s''',
        'code':'''.text
_start:
    movia   r4, 0xFF200000
    movia   r5, 0xFF200040

loop:
    ldwio   r6, 0(r5)


    stwio   r6, 0(r4)
    br      loop
''',
        'checker': check_proj1
    },
    ##########
    # Linked list sum
    'list-sum': {
        'public': True,
        'title': 'Sum a Linked List',
        'diff':  'medium',
        'desc': '''You are given a linked list node at addr <code>HEAD</code>.
                   Each list node consists of a word <code>next</code> that points to
                   the next node in the list, followed by a word <code>value</code>. The last
                   node in the list has its <code>next</code> pointer set to 0 (NULL).<br/><br/>

                   You can think of each node as being equivalent to the following C struct:<br/>
<pre>struct node {
    struct node *next;
    int          value;
};</pre><br/><br/>

                   Your task is to find the sum of all the <code>value</code>s in the list,
                   and write this sum to <code>SUM</code>,
                   then call the <code>break</code> instruction''',
        'code':'''.text
_start:


.data
SUM:    .word 0
HEAD:   .word N1, 5
N1:     .word N2, 3
N2:     .word N3, 10
N3:     .word 0,  6
''',
        'checker': check_list_sum
    },
    ############
    # Fib
    'fibonacci': {
        'public': True,
        'title': 'Fibonacci Sequence',
        'diff':  'medium',
        'desc':  '''The  Fibonacci Sequence is computed as <code>f(n) = f(n-1) + f(n-2)</code>. We must define two <b>base case</b> values: <code>f(0) = 0</code> and <code>f(1) = 1</code>.<br/><br/>

                Thus, the first values of this sequence are: 0, 1, 1, 2, 3, 5, 8, 13, 21, 34, etc.<br/><br/>

                Your task is to write a function <code>fib</code> which takes a single number <code>n</code> and returns <code>f(n)</code> as defined above by the Fibonacci Sequence.''',
        'code':'''.text
fib:
    # Write your code here

    ret

_start:
    # You should probably test your program!
    # Feel free to change the value of N, but leave the rest of
    # this code as is.
    movia   sp, 0x04000000  # Setup the stack pointer
    subi    sp, sp, 4

    movia   r4, N
    ldw     r4, 0(r4)

    call    fib             # fib(N)

    movia   r4, F
    stw     r2, 0(r4)       # store r2 to F
    break                   # r2 should be 55 here.
.data
N:  .word 10
F:  .word 0
''',
        'checker': check_fib
    },
    #########
    # Sort
    'sort': {
        'public': True,
        'title': 'Sort an array',
        'diff': 'hard',
        'desc': '''You are given an array of <b>signed</b> words starting at <code>SORT</code> that contains <code>N</code> words. Your task is to <b>sort</b> this array, overwriting the current array with one that is sorted. Once done, your code should call the <code>break</code> instruction.<br/><br/>
                We suggest you implement a very simple in-place sort, such as <a href="https://en.wikipedia.org/wiki/Bubble_sort">Bubble sort</a>, but you are welcome to implement any sorting algorithm.''',
        'code':'''.text
_start:


.data
N: .word 5
SORT: .word 8, 3, 7, 2, 9
# Padding
.rept 100 .word 0
.endr''',
        'checker': check_sort
    },
}


@get('/nios2/examples/<eid>')
@jinja2_view('example.html')
def get_example(eid):
    gc.collect()
    if eid not in exercises:
        return {'asm_error': 'Exercise ID not found'}
    ex = exercises[eid]

    return {'eid': eid,
            'exercise_title': ex['title'],
            'exercise_desc':  ex['desc'],
            'exercise_code':  ex['code'],
           }


@post('/nios2/examples/<eid>')
@jinja2_view('example.html')
def post_example(eid):
    gc.collect()
    asm = request.forms.get('asm')
    obj = nios2_as(asm.encode('utf-8'))

    if eid not in exercises:
        return {'asm_error': 'Exercise ID not found'}

    ex = exercises[eid]

    if not(isinstance(obj, dict)):
        return {'eid': eid, \
                'exercise_code': asm,\
                'exercise_title': ex['title'],\
                'exercise_desc':  ex['desc'],\
                'asm_error': obj,}

    if '_start' not in obj['symbols']:
        return {'eid': eid, \
                'exercise_code': asm,\
                'exercise_title': ex['title'],\
                'exercise_desc':  ex['desc'],\
                'asm_error': 'No _start in your code (did you forget to enter instructions?)<br/>%s' % (json.dumps(obj)),}

    extra_info = ''
    res = ex['checker'](obj)
    if len(res) == 2:
        success, feedback = res
    elif len(res) == 3:
        success, feedback, extra_info = res

    if extra_info is None:
        extra_info = ''

    return {'eid': eid,
            'exercise_code': asm,
            'exercise_title': ex['title'],
            'exercise_desc':  ex['desc'],
            'feedback': feedback,
            'success': success,
            'extra_info': extra_info,
            }

@post('/nios2/examples.moodle/<eid>/<uid>')
def post_moodle(eid,uid):
    gc.collect()
    asm = request.forms.get('asm')
    obj = nios2_as(asm.encode('utf-8'))

    if eid not in exercises:
        return 'Exercise ID not found'

    ex = exercises[eid]

    if not(isinstance(obj, dict)):
        return 'Error: %s' % obj

    if '_start' not in obj['symbols']:
        return 'No _start in your code (did you forget to enter instructions?\n%s' % (json.dumps(obj))

    #success, feedback = ex['checker'](obj)
    res = ex['checker'](obj)
    if len(res) == 2:
        success, feedback = res
    elif len(res) == 3:
        success, feedback, _ = res

    return 'Passed(%s): %s\n%s' % (uid, success, feedback)


@get('/nios2')
@jinja2_view('index.html')
def nios2():
    return {'exercises': exercises}



@route('/nios2/static/<path:path>')
def serve_static(path):
    return static_file(path, root="static/")


debug(True)
if __name__ == '__main__':
    debug(True)
    run(reloader=True)
