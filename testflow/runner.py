    #Version:1.1.2
    #================================================================================
    #                                   DISCLAIMER
    #================================================================================
    # Copyright (c) 2025 ATOMS / TestFlow
    # Licensed under the TestFlow Community License (TCL).
    # This file may be used internally for testing and evaluation only.
    # Commercial use, redistribution, or competitive use is strictly prohibited.
    # For details, see the LICENSE file in the project root.
    #--------------------------------------------------------------------------------
    #                                www.atomsai.net
    #--------------------------------------------------------------------------------
    #                               © ATOMS | TestFlow
    #================================================================================
    

import pyvisa
import serial
import re
import time
import sys
import csv
import os
import threading
import ast
import operator
from pathlib import Path
import json
from datetime import datetime
from typing import Dict, List, Any
from typing import Optional, Dict, Any


# Global variables for progress tracking
_CURRENT_STEP = 0
_TOTAL_STEPS = 0
code_version= "Version:1.1.0"
# Serial communication constants
BAUDRATE = 115200

# Global in-memory log list to store execution logs
_TESTFLOW_LOGS = []

stop_event = threading.Event()
pause_event = threading.Event()
debug_event = threading.Event()

from colorama import init, Back, Fore, Style
init()  # enables ANSI support on Windows 
    
def run_script(script_path: str, output_path: str, debug_mode: bool=False):

    # =================================================================================
    # Send SCPI Commands and Queries
    # =================================================================================
    def send_scpi_command(visa_address: str, command: str):
        """Sends a SCPI command to a VISA instrument."""
        try:
            rm = pyvisa.ResourceManager()
            instrument = rm.open_resource(visa_address)
            instrument.write(command)
            instrument.close()
        except Exception as e:
            log_print(f"\033[31mTestFlow says Error: {e}\033[0m")


    def send_scpi_query(visa_address: str, query: str):
        """
        Sends a SCPI query to the instrument and returns the reply.
        """
        try:
            rm = pyvisa.ResourceManager()
            instrument = rm.open_resource(visa_address)
            reply = instrument.query(query)
            reply_stripped = reply.strip() if isinstance(reply, str) else reply
            instrument.close()
            return reply_stripped
        except Exception as e:
            log_print(f"\033[31mTestFlow says Error: {e}\033[0m")
            return None


    # =================================================================================
    # Serial Communication Functions
    # =================================================================================
    def send_serial_command(serial_port: str, command: str):
        """Sends a command to a serial device (MCU)."""
        try:
            with serial.Serial(serial_port, BAUDRATE, timeout=1) as ser:
                # Send the command with newline for STM32 parsing
                ser.write((command.strip() + '\r\n').encode())
                time.sleep(0.1)  # Small delay for processing
        except Exception as e:
            log_print(f"\033[31mTestFlow says Error: {e}\033[0m")


    def send_serial_query(serial_port: str, query: str):
        """
        Sends a query to a serial device (MCU) and returns the reply.
        """
        try:
            with serial.Serial(serial_port, BAUDRATE, timeout=1) as ser:
                # Send the command with newline for STM32 parsing
                ser.write((query.strip() + '\r\n').encode())
                time.sleep(0.1)  # Small delay for STM32 to process and reply
                reply = ser.read_all().decode(errors='ignore')
                return reply.strip()
        except Exception as e:
            log_print(f"\033[31mTestFlow says Error: {e}\033[0m")
            return None


    # =================================================================================
    # Script Utility Functions
    # =================================================================================
    def count_script_lines(script_path: str) -> int:
        """Counts total number of lines in the script."""
        try:
            with open(script_path, 'r', encoding='utf-8') as file:
                lines = file.readlines()
            return len(lines)
        except Exception as e:
            log_print(f"\033[31mError reading script: {e}\033[0m")
            return 0


    def read_line_from_script(script_path: str, line_number: int) -> str:
        """Reads a specific line from the script file."""
        try:
            with open(script_path, 'r', encoding='utf-8') as file:
                lines = file.readlines()
            if 1 <= line_number <= len(lines):
                return lines[line_number - 1].strip()
            else:
                return f"Line {line_number} is out of range. Total lines: {len(lines)}"
        except Exception as e:
            return f"Error reading script: {e}"


    def extract_prefixed_line(line: str, prefix: str) -> str:
        """Extracts text from a line if it starts with a given prefix."""
        if isinstance(line, str) and line.strip().startswith(prefix):
            return line.strip()[len(prefix):].strip()
        return ""


    def check_line_prefix(line: str, prefix: str) -> int:
        """Checks if a line starts with a given prefix."""
        if isinstance(line, str) and line.strip().startswith(prefix):
            return 1
        return 0


    def has_variable(line: str) -> int:
        """Checks if a line contains a variable placeholder ${var}."""
        if isinstance(line, str):
            match = re.search(r"\$\{[^}]+\}", line)
            return 1 if match else 0
        return 0


    def has_question_mark(line: str) -> bool:
        """Checks if a line contains a '?' (indicating a query command)."""
        if not isinstance(line, str):
            return False
        return "?" in line



    # =================================================================================
    # Variables Parsing and Replacement
    # =================================================================================
    def parse_variable_ranges(lines: list[str], start_index: int) -> tuple[str, list[float]]:
        """Parses Variable/Range blocks in the script."""
        if not lines[start_index].strip().startswith("Variable:"):
            raise ValueError("Line at start_index does not start with 'Variable:'")

        var_name = lines[start_index].strip().split("Variable:")[1].strip()
        values = []

        i = start_index + 1
        while i < len(lines):
            line = lines[i].strip()
            # Check for both "Range:" and "Range(1/2):" patterns
            if not (line.startswith("Range:") or (line.startswith("Range(") and "):" in line)):
                break

            # Extract the range definition after the colon
            if line.startswith("Range:"):
                range_def = line.split("Range:")[1].strip()
            else:
                # Handle numbered ranges like "Range(1/2):"
                range_def = line.split("):", 1)[1].strip()
            match_parts = re.match(r"\((\d+),\s*(\d+)\)\s*,\s*(.*)", range_def)
            if not match_parts:
                raise ValueError(f"Invalid Range format: {line}")

            start_iter = int(match_parts.group(1))
            end_iter = int(match_parts.group(2))
            num_points = end_iter - start_iter + 1
            value_part = match_parts.group(3).strip()

            if value_part.startswith("("):
                # Sweep values (start, end, step)
                match_vals = re.match(r"\(([^,]+),([^,]+),([^)]+)\)", value_part)
                val_start = float(match_vals.group(1))
                val_end = float(match_vals.group(2))
                step = float(match_vals.group(3))

                sweep_values = []
                current = val_start
                for _ in range(num_points):
                    sweep_values.append(round(current, 10))
                    current += step
                    if (step > 0 and current > val_end) or (step < 0 and current < val_end):
                        current = val_end
                values.extend(sweep_values[:num_points])
            else:
                # Constant value range
                constant_value = float(value_part)
                values.extend([constant_value] * num_points)

            i += 1

        return var_name, values


    def get_all_variable_arrays(
        script_path: str,
        start_line: int = 1,
        end_line: int | None = None,
        ) -> Dict[str, Dict[str, Any]]:
        """
        Scans the script and builds a dictionary of all variables and their values,
        but ONLY between start_line and end_line (1-based, inclusive).

        Returns:
          {
            var_name: {
              'values': List[Any],
              'current_value': Any
            },
            ...
          }
        """
        variable_arrays: Dict[str, Dict[str, Any]] = {}

        try:
            with open(script_path, 'r', encoding='utf-8') as f:
                lines: List[str] = f.readlines()

            n = len(lines)
            if n == 0:
                return variable_arrays

            # Clamp the scan window to file bounds (1-based -> 0-based indices)
            if start_line is None or start_line < 1:
                start_line = 1
            if end_line is None or end_line > n:
                end_line = n
            if start_line > end_line:
                # Nothing to scan
                return variable_arrays

            i = start_line - 1  # 0-based index
            end_idx = end_line  # exclusive in while condition

            while i < end_idx:
                line = lines[i].strip()

                if line.startswith("Variable:"):
                    # NOTE: This assumes parse_variable_ranges(lines, i) does not
                    # read past end_idx in a harmful way. If you need a *hard*
                    # bound, consider adding a bounded version of the parser.
                    var_name, var_values = parse_variable_ranges(lines, i)

                    if var_values:
                        variable_arrays[var_name] = {
                            'values': var_values,
                            'current_value': var_values[0]
                        }
                    else:
                        variable_arrays[var_name] = {
                            'values': [],
                            'current_value': None
                        }

                i += 1

        except Exception as e:
            log_print(f"\033[31mError parsing variable arrays: {e}\033[0m")

        return variable_arrays




    def replace_variables_with_current_values(line: str, variable_arrays: dict) -> str:
        """Replaces variable placeholders in a line with their current values."""
        if not isinstance(line, str):
            return line

        matches = re.findall(r"\$\{([^}]+)\}", line)
        for var_name in matches:
            if var_name in variable_arrays:
                current_value = variable_arrays[var_name]['current_value']
                pattern = re.compile(rf"\$\{{\s*{re.escape(var_name)}\s*\}}")
                line = pattern.sub(str(current_value), line)
        return line


    # =================================================================================
    # Loops Parsing
    # =================================================================================


    def get_loop_end_number(line: str) -> int:
        """Extracts loop number from a 'Loop_end(...)' line."""
        line = line.strip()
        match = re.match(r"Loop_end\((\d+)\)", line)
        return int(match.group(1)) if match else None


    def wait_time_is(line: str) -> int:
        """Extracts wait time in ms from 'wait(x)' command."""
        match = re.search(r"wait\((\d+)\)", line.strip(), re.IGNORECASE)
        return int(match.group(1)) if match else 0


    def _parse_wait_ms(line: str) -> int:
        """Parse wait time from wait(x) command."""
        match = re.search(r"wait\((\d+)\)", line.strip(), re.IGNORECASE)
        return int(match.group(1)) if match else None


    def _parse_delay_ms(line: str) -> int:
        """Parse delay time from DELAY: command."""
        try:
            line_clean = line.strip().upper()
            if not line_clean.startswith("DELAY:"):
                return None
            parts = line_clean.replace("DELAY:", "").strip().split(",")
            time_value = float(parts[0])
            unit = "MS" if len(parts) == 1 else parts[1].strip()
            if unit == "MS":
                return int(time_value)
            elif unit == "S":
                return int(time_value * 1000)
            elif unit == "M":
                return int(time_value * 60 * 1000)
            elif unit == "H":
                return int(time_value * 60 * 60 * 1000)
            else:
                return int(time_value)
        except Exception:
            return None


    def _fmt_hms_ms(total_ms: int) -> str:
        """Format milliseconds as HH:MM:SS."""
        total_seconds = total_ms // 1000
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        seconds = total_seconds % 60
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


    def analyze_steps_and_time(script_path: str):
        """
        Steps are based ONLY on loop structure:
          - Sum sequential loops
          - Multiply nested loops
          - If no loops, steps = 1
        Time is the sum of (wait/delay) * multiplicity of active loops.

        Returns:
          {
            'total_steps': int,
            'total_time_ms': int,
            'total_time_hms': str
          }
        """
        with open(script_path, "r", encoding="utf-8") as f:
            lines = [ln.strip() for ln in f if ln.strip() and not ln.strip().startswith("//")]

        re_loop_start = re.compile(r"Loop_start\((\d+)\)\s*:\s*(\d+)")
        re_loop_end   = re.compile(r"Loop_end\((\d+)\)")

        # Each stack item: {'iters': int, 'has_child': bool}
        stack = []
        total_steps = 0
        total_time_ms = 0

        def current_multiplier():
            mult = 1
            for item in stack:
                mult *= item['iters']
            return mult

        for line in lines:
            # Loop start
            m_s = re_loop_start.match(line)
            if m_s:
                # mark parent as having a child (so parent won't be counted as leaf)
                if stack:
                    stack[-1]['has_child'] = True
                stack.append({'iters': int(m_s.group(2)), 'has_child': False})
                continue

            # Loop end
            m_e = re_loop_end.match(line)
            if m_e:
                if stack:
                    # If this loop has no child loops, it's a leaf: count its iterations * all parents
                    if not stack[-1]['has_child']:
                        total_steps += current_multiplier()  # includes this loop
                    stack.pop()
                continue

            # Time-bearing commands (do NOT affect steps)
            wait_ms = _parse_wait_ms(line)
            if wait_ms is not None:
                total_time_ms += wait_ms * (current_multiplier() or 1)
                continue

            delay_ms = _parse_delay_ms(line)
            if delay_ms is not None:
                total_time_ms += delay_ms * (current_multiplier() or 1)
                continue

        # If there were NO loops at all, steps = 1 (single pass script)
        if total_steps == 0 and not any(re_loop_start.match(l) for l in lines):
            total_steps = 1

        return {
            'total_steps': total_steps,
            'total_time_ms': total_time_ms,
            'total_time_hms': _fmt_hms_ms(total_time_ms)
        }


    # =================================================================================
    # VISA Validation
    # =================================================================================

    def validate_visa_connections(script_path: str):
        """Ensures all VISA addresses in script are connected, else exits program."""
        visa_addresses_in_script = set()
        disconnected_addresses = []

        # 1) Extract VISA addresses from script
        try:
            with open(script_path, 'r', encoding='utf-8') as f:
                for line in f:
                    # First, handle the INST:: <visa address> pattern explicitly
                    if "INST::" in line:
                        after = line.split("INST::", 1)[1].strip()
                        # Strip quotes and trailing comments if any
                        after = after.split("#", 1)[0].strip()
                        addr = after.strip().strip('"').strip("'")
                        if addr:
                            visa_addresses_in_script.add(addr)

                    # Also keep the old generic matcher as a backup
                    matches = re.findall(
                        r'\b(?:V\d{6}|USB[^\s"]+|TCPIP[^\s"]+|GPIB[^\s"]+)',
                        line
                    )
                    visa_addresses_in_script.update(matches)

        except Exception as e:
            log_print(f"\033[31mError reading script: {e}\033[0m")
            sys.exit(1)

        # If script doesn't reference any VISA addresses, don't claim "all connected"
        if not visa_addresses_in_script:
            log_print("\033[31m No VISA instruments found in script. Skipping VISA connection validation.\033[0m")
            return

        # 2) Query connected VISA resources
        try:
            rm = pyvisa.ResourceManager()
            connected_resources = rm.list_resources()
        except Exception as e:
            log_print(f"\033[31mError accessing VISA instruments: {e}\033[0m")
            sys.exit(1)

        # If script needs instruments but none are connected at all
        if not connected_resources:
            log_print(" \033[31mError: Script requires VISA instruments, but none are connected.\033[0m")
            for addr in sorted(visa_addresses_in_script):
                log_print(f" - {addr}")
            sys.exit("Missing required VISA connections.")

        # 3) Compare required vs connected
        for addr in visa_addresses_in_script:
            if addr not in connected_resources:
                disconnected_addresses.append(addr)

        if disconnected_addresses:
            log_print(" \033[31mError: The following VISA instruments are not connected:\033[0m")
            for dev in disconnected_addresses:
                log_print(f" - {dev}")
            sys.exit("Missing required VISA connections.")
        else:
            log_print(" \033[32mAll VISA instruments in script are connected.\033[0m")

    # =================================================================================
    # Utility Functions: Action titles, delays, node parsing
    # =================================================================================
    def get_action_title(line: str) -> str:
        """Extracts action title from '#ACTION: (title)' line."""
        match = re.match(r"#ACTION:\s*\(([^)]+)\)", line.strip(), re.IGNORECASE)
        return match.group(1) if match else None


    def get_delay_in_ms(line: str) -> int:
        """Parses 'DELAY: x,unit' into milliseconds."""
        try:
            line_clean = line.strip().upper()
            if not line_clean.startswith("DELAY:"):
                return 10  # default delay
            parts = line_clean.replace("DELAY:", "").strip().split(",")
            time_value = float(parts[0])
            unit = "MS" if len(parts) == 1 else parts[1].strip().upper()

            if unit == "MS":
                return int(time_value)
            elif unit == "S":
                return int(time_value * 1000)
            elif unit == "M":
                return int(time_value * 60 * 1000)
            elif unit == "H":
                return int(time_value * 60 * 60 * 1000)
            else:
                log_print(f"⚠ Unknown unit '{unit}', assuming milliseconds.")
                return int(time_value)
        except Exception as e:
            log_print(f"\033[31mError parsing delay line: {e}\033[0m")
            return 10  # fallback default


        
    # =================================================================================
    # ASCII Banners
    # =================================================================================
    def print_big_testflow_banner():
        """Prints big ASCII banner for TestFlow start."""
        # Print TestFlow ASCII art banner and legal/info lines using the unified logger
        
        log_print_panner( Fore.GREEN +r"""
████████╗███████╗███████╗████████╗      ███████╗██╗      ██████╗ ██╗    ██╗
╚══██╔══╝██╔════╝██╔════╝╚══██╔══╝      ██╔════╝██║     ██╔═══██╗██║    ██║
   ██║   █████╗  ███████╗   ██║    ███  █████╗  ██║     ██║   ██║██║ █╗ ██║
   ██║   ██╔══╝  ╚════██║   ██║         ██╔══╝  ██║     ██║   ██║██║███╗██║
   ██║   ███████╗███████║   ██║         ██╗     ███████╗╚██████╔╝╚███╔███╔╝
   ╚═╝   ╚══════╝╚══════╝   ╚═╝         ╚═╝     ╚══════╝ ╚═════╝  ╚══╝╚══╝ 
        """+ Style.RESET_ALL)
        # Visual separators and centered disclaimer text
        log_print_panner(Fore.GREEN +"=" * 80)
        log_print_panner("DISCLAIMER".center(80))
        log_print_panner("=" * 80)
        # Legal / ownership text centered to match the banner style
        log_print_panner("Copyright (c) 2025 ATOMS / TestFlow".center(80))
        log_print_panner("Licensed under the TestFlow Community License (TCL).".center(80))
        log_print_panner("This file may be used internally for testing and evaluation only.n".center(80))
        log_print_panner("Commercial use, redistribution, or competitive use is strictly prohibited.".center(80))
        # Horizontal rules and site/brand lines
        log_print_panner("-" * 80)
        log_print_panner("www.atomsai.net".center(80))
        log_print_panner("-" * 80)
        log_print_panner("© ATOMS | TestFlow".center(80))
        log_print_panner("=" * 80)
        # Blank line for spacing
        log_print_panner((datetime.now().strftime("%Y-%m-%d %H:%M:%S")).center(80))
        log_print_panner("=" * 80+ Style.RESET_ALL)
        

    def print_big_testdone_banner():
        """
        Prints 'Test Done' in a decorative big ASCII style using *, -, and #.
        """
        # Print a completion banner to indicate the end of a TestFlow run
        log_print_panner(Fore.GREEN +r"""
████████╗███████╗███████╗████████╗     ██████╗   ██████╗ ███╗   ██╗███████╗
╚══██╔══╝██╔════╝██╔════╝╚══██╔══╝     ██╔═══██╗██╔═══██╗████╗  ██║██╔════╝
   ██║   █████╗  ███████╗   ██║        ██║   ██║██║   ██║██╔██╗ ██║█████╗  
   ██║   ██╔══╝  ╚════██║   ██║        ██║   ██║██║   ██║██║╚██╗██║██╔══╝  
   ██║   ███████╗███████║   ██║        ██████ ╔╝╚██████╔╝██║ ╚████║███████╗
   ╚═╝   ╚══════╝╚══════╝   ╚═╝          ╚════╝  ╚═════╝ ╚═╝  ╚═══╝╚══════╝
            """+ Style.RESET_ALL)

    def print_big_teststopped_banner():
        """
        Prints 'Test Stopped' in a decorative big ASCII style using *, -, and #.
        """
        # Print a banner to indicate the test was stopped manually or by error
        log_print_panner(Fore.RED +r"""
████████╗███████╗███████╗████████╗     ███████╗████████╗ ██████╗ ██████╗ ██████╗ ███████╗██████╗  
╚══██╔══╝██╔════╝██╔════╝╚══██╔══╝     ██╔════╝╚══██╔══╝██╔═══██╗██╔══██╗██╔══██╗██╔════╝██╔═══██╗
   ██║   █████╗  ███████╗   ██║        ███████╗   ██║   ██║   ██║██████╔╝██████╔╝█████╗  ██║   ██║
   ██║   ██╔══╝  ╚════██║   ██║        ╚════██║   ██║   ██║   ██║██╔══   ██╔══   ██╔══╝  ██║   ██║
   ██║   ███████╗███████║   ██║        ███████║   ██║   ╚██████╔╝██║     ██║     ███████╗██████ ╔╝
   ╚═╝   ╚══════╝╚══════╝   ╚═╝        ╚══════╝   ╚═╝    ╚═════╝ ╚═╝     ╚═╝     ╚══════╝  ╚════╝
            """+ Style.RESET_ALL)


    def parse_node_line(line: str) -> dict:
        """
        Parses a #NODE line and extracts node number, type, and optional instrument info.
        
        Args:
            line (str): The line from the script starting with #NODE.
        
        Returns:
            dict: {
                'node_number': int,
                'node_type': str,
                'instrument_name': str,
                'manufacturer': str,
                'model': str
            }
        """
        # Initialize the return structure with safe defaults
        result = {
            'node_number': None,
            'node_type': '',
            'instrument_name': '',
            'manufacturer': '',
            'model': ''
        }

        try:
            # Match the #NODE <num> (<type>, <instrument>, <mfr>, <model>) pattern
            match = re.match(r"#NODE\s*(\d+)\s*\((.*?)\)", line)
            if match:
                # Extract node number (as int) and the descriptor section inside parentheses
                result['node_number'] = int(match.group(1))
                node_type_and_rest = match.group(2).strip()

                # Split comma-separated fields; each is optional after the first
                parts = [p.strip() for p in node_type_and_rest.split(',')]

                # Fill fields if present; otherwise keep defaults
                result['node_type'] = parts[0] if len(parts) > 0 else ''
                result['instrument_name'] = parts[1] if len(parts) > 1 else ''
                result['manufacturer'] = parts[2] if len(parts) > 2 else ''
                result['model'] = parts[3] if len(parts) > 3 else ''

        except Exception as e:
            # Non-fatal: log parse errors and return defaults
            log_print(f"\033[31mError parsing node line: {e}\033[0m")

        return result


    def _sanitize_title(s: str) -> str:
        """Make action titles safer for CSV headers (remove spaces/commas etc.)."""
        # Strip outer whitespace
        s = s.strip()
        # Replace internal whitespace sequences with underscores for compact headers
        s = re.sub(r"\s+", "_", s)
        # Remove any non word/hyphen characters to avoid CSV header issues
        s = re.sub(r"[^\w\-]+", "", s)  # keep letters, digits, underscore, hyphen
        return s


    def build_csv_headers_from_script(script_path: str) -> list[str]:
        """
        Build CSV header based on the ATOMS script contents.

        Header format:
          1) 'N'
          2) 'Loop(N)' for each loop number found
          3) '<variable>' for each variable defined
          4) 'Node<N>Action<A><ActionTitle>' for each action that has at least one 'CMD:' with '?'
          5) 'Date'
          6) 'Time'
        """
        # Read script fully as a list of raw lines (strip only trailing newline)
        with open(script_path, "r", encoding="utf-8") as f:
            lines = [ln.rstrip("\n") for ln in f]

        # Start header with row counter column
        header = ["N"]

        # 2) Collect unique loop numbers from 'Loop_start(<n>): <iterations>'
        loop_numbers = []
        for ln in lines:
            m = re.match(r"\s*Loop_start\((\d+)\)\s*:\s*(\d+)", ln)
            if m:
                n = int(m.group(1))
                if n not in loop_numbers:
                    loop_numbers.append(n)
        # Append Loop(n) columns in ascending loop number order
        for n in sorted(loop_numbers):
            header.append(f"Loop({n})")

        # 3) Collect unique variable names from 'Variable: <name>'
        variables = []
        for ln in lines:
            if ln.strip().startswith("Variable:"):
                name = ln.split("Variable:", 1)[1].strip()
                if name and name not in variables:
                    variables.append(name)
        header.extend(variables)

        # 4) Build action-based measurement columns (only if any CMD line contains '?')
        # Track per-node action indices and current parsing state
        action_cols = []
        current_node = None
        action_index_per_node = {}
        in_action = False
        current_action_title = None
        action_has_query = False  # set True if any CMD line with '?' appears in current action
        action_command_types = set()  # Track what types of commands this action has

        # Helper to finalize an action column (if it had a query)
        def _flush_action_column():
            nonlocal current_node, current_action_title, action_has_query, action_command_types
            if current_node is not None and current_action_title and action_has_query:
                # Sanitize title and form column like '<Title>(N<node>|A<idx>)'
                safe_title = _sanitize_title(current_action_title)
                
                # Check what types of commands this action has
                base_col_name = f"{safe_title}(N{current_node}|A{action_index_per_node[current_node]})"
                
                # Add base column for queries
                if 'query' in action_command_types:
                    if base_col_name not in action_cols:
                        action_cols.append(base_col_name)
                
                # Add img column for PNG commands
                if 'png' in action_command_types:
                    img_col_name = f"{safe_title}img(N{current_node}|A{action_index_per_node[current_node]})"
                    if img_col_name not in action_cols:
                        action_cols.append(img_col_name)
                
                # Add set column for SET commands
                if 'set' in action_command_types:
                    set_col_name = f"{safe_title}set(N{current_node}|A{action_index_per_node[current_node]})"
                    if set_col_name not in action_cols:
                        action_cols.append(set_col_name)

        # Single pass over lines to detect nodes/actions and whether actions contain queries
        for ln in lines:
            s = ln.strip()

            # Node start resets action state and sets current node number
            m_node = re.match(r"#NODE\s*(\d+)\s*\(", s)
            if m_node:
                # Close any open action before switching node
                if in_action:
                    _flush_action_column()
                    in_action = False
                    current_action_title = None
                    action_has_query = False
                    action_command_types.clear()

                current_node = int(m_node.group(1))
                action_index_per_node.setdefault(current_node, 0)
                continue

            # Action start within the current node
            m_act = re.match(r"#ACTION:\s*\(([^)]+)\)", s, re.IGNORECASE)
            if m_act:
                # Close previous action (if any) before starting new one
                if in_action:
                    _flush_action_column()

                in_action = True
                current_action_title = m_act.group(1).strip()
                action_has_query = False
                action_command_types.clear()  # Reset command types for new action
                # Increment the action count for this node to tag columns uniquely
                if current_node is not None:
                    action_index_per_node[current_node] += 1
                continue

            # While inside an action, detect if any command line is a query ('?') or PNG/SET/QRY
            if in_action:
                if s.startswith("CMD:") and "?" in s:
                    action_has_query = True
                    action_command_types.add('query')
                    continue
                elif s.startswith("QRY:"):
                    action_has_query = True  # QRY commands also create columns
                    action_command_types.add('query')
                    continue
                elif s.startswith("PNG:"):
                    action_has_query = True  # PNG commands also create columns
                    action_command_types.add('png')
                    continue
                elif s.startswith("SET:"):
                    action_has_query = True  # SET commands also create columns
                    action_command_types.add('set')
                    continue
                elif s.startswith("SER:"):
                    if "?" in s:
                        action_has_query = True  # SER commands with queries create columns
                        action_command_types.add('serial_query')
                    else:
                        action_command_types.add('serial')
                    continue

            # Optional explicit node end; also flush any pending action column
            if s.startswith("#END_NODE"):
                if in_action:
                    _flush_action_column()
                    in_action = False
                    current_action_title = None
                    action_has_query = False
                    action_command_types.clear()
                current_node = None
                continue

        # If file ended while still inside an action, finalize it
        if in_action:
            _flush_action_column()

        # Append all discovered action columns (query-based)
        header.extend(action_cols)

        # 5) and 6) Always add Date and Time columns at the end
        header.append("Date")
        header.append("Time")

        return header


    def create_csv_file(file_path: str, script_path: str, temp_csv: bool = False):
        """
        Creates a CSV file for TestFlow output.
        If file_path is a directory, a default name Out<YYYY-MM-DD>_<HHMM>.csv is used.
        If temp_csv is True, the generated filename is prefixed with 'temp'.
        """
        # Check if path is a directory-like input
        is_dir_like = os.path.isdir(file_path) or file_path.endswith(os.sep)

        if is_dir_like:
            # Generate default filename with timestamp
            now_str = datetime.now().strftime("%Y-%m-%d_%H%M")
            base_name = f"Out{now_str}.csv"
            if temp_csv:
                base_name = f"temp_{base_name}"
            file_path = os.path.join(file_path, base_name)
        else:
            # Caller passed a full file path; optionally prefix basename with 'temp'
            if temp_csv:
                dir_name = os.path.dirname(file_path) or "."
                base_name = os.path.basename(file_path)
                # Avoid double-prefixing
                if not base_name.startswith("temp"):
                    base_name = f"temp{base_name}"
                file_path = os.path.join(dir_name, base_name)

        # Ensure the directory for the file exists
        os.makedirs(os.path.dirname(file_path), exist_ok=True)

        # Generate CSV column headers based on the script structure
        headers = build_csv_headers_from_script(script_path)

        # Open the file and write the header row as the first line
        with open(file_path, mode="w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(headers)

        # Create a dictionary mapping header names to their column indices
        header_index_map = {h: i for i, h in enumerate(headers)}

        # Extract the filename (without extension) for later use in logs/references
        filename_no_ext = os.path.splitext(os.path.basename(file_path))[0]

        log_print(f"[INFO] CSV file created: {file_path}")
        return file_path, filename_no_ext, header_index_map

    def safe_read_csv(file_path, retries=100, delay=1):
        """
        Safely reads a CSV file into memory.
        Automatically retries if the file is locked (e.g., open in Excel).
        """

        for attempt in range(1, retries + 1):
            try:
                with open(file_path, mode="r", newline="", encoding="utf-8") as f:
                    return list(csv.reader(f))

            except PermissionError:
                print(f"\033[31m[Warning] File is open or locked. Cannot read yet: {os.path.basename(file_path)}\033[0m")
                print(f"\033[31mRetrying in {delay} seconds... (attempt {attempt}/{retries})\033[0m")
                time.sleep(delay)

            except Exception as e:
                print(f"\033[31m[Error] Unexpected error reading file: {e}\033[0m")
                raise e

        # If we exhausted all retries
        raise PermissionError(
            f"\033[31mCould not read '{file_path}' because it remained locked after {retries} attempts.\033[0m"
        )
        
    def safe_write_csv(file_path, rows, retries=100, delay=1):
        """
        Safely writes rows to a CSV file.
        Automatically retries if the file is locked (e.g., open in Excel).
        Writes into a temporary file then atomically replaces the original.
        """
        temp_path = file_path + ".tmp"

        for attempt in range(1, retries + 1):
            try:
                # 1) Write to a temporary file (always succeeds if *you* are not locking it)
                with open(temp_path, mode="w", newline="", encoding="utf-8") as f:
                    writer = csv.writer(f)
                    writer.writerows(rows)

                # 2) Try replacing the original (THIS is the step that fails when file is open)
                os.replace(temp_path, file_path)

                return  # Success!

            except PermissionError:
                # Clean up temp file
                if os.path.exists(temp_path):
                    try:
                        os.remove(temp_path)
                    except:
                        pass

                print(f"[Warning] '{os.path.basename(file_path)}' is currently open or locked.")
                print(f"Retrying in {delay} seconds... (attempt {attempt}/{retries})")
                time.sleep(delay)

            except Exception as e:
                if os.path.exists(temp_path):
                    try:
                        os.remove(temp_path)
                    except:
                        pass
                print(f"\033[31m[Error] Unexpected write error: {e}\033[0m")
                raise

        raise PermissionError(
            f"\033[31mCould not write to '{file_path}' — it remained locked after {retries} retries.\033[0m"
        )
    
    def update_csv_cell(file_path: str, row_index: int, column, value):
        """
        Updates a specific cell in a CSV file by row and column.
        """
        column = _sanitize_title(column)
        # Ensure the CSV file exists
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"CSV file not found: {file_path}")

        # Read the full file into memory (list of rows)
        reader = safe_read_csv(file_path)

        # If column is specified by name, resolve its index from the header row
        if isinstance(column, str):
            header = reader[0]
            if column not in header:
                raise ValueError(f"Column '{column}' not found in CSV.")
            col_index = header.index(column)
        else:
            col_index = int(column)

        # If requested row does not exist yet, expand with empty rows
        while len(reader) <= row_index:
            reader.append([""] * len(reader[0]))

        # Update the cell with the new value (always store as string)
        reader[row_index][col_index] = str(value)

        # Rewrite the entire CSV file with updated content
        safe_write_csv(file_path, reader)




    def set_total_steps(total: int):
        """Set the total number of steps for progress tracking."""
        global _TOTAL_STEPS
        _TOTAL_STEPS = total

    def increment_step():
        """Increment the current step counter."""
        global _CURRENT_STEP
        _CURRENT_STEP += 1

    def set_current_step(step: int):
        """Set the current step directly."""
        global _CURRENT_STEP
        _CURRENT_STEP = step

    def get_progress_info():
        """Get current progress information."""
        progress_percent = 0
        if _TOTAL_STEPS > 0:
            progress_percent = min(int((_CURRENT_STEP / _TOTAL_STEPS) * 100), 100)
        return _CURRENT_STEP, _TOTAL_STEPS, progress_percent

    def log_print(*args, sep=" ", end="\n"):
        """
        Prints to terminal and logs the same message for later saving.
        Now includes progress information at the beginning of each line.
        """
        # Calculate progress percentage
        progress_percent = 0
        if _TOTAL_STEPS > 0:
            progress_percent = min(int((_CURRENT_STEP / _TOTAL_STEPS) * 100), 100)
        
        # Create progress prefix
        progress_prefix = f"[PROGRESS:{progress_percent:3d}%|{_CURRENT_STEP:4d}/{_TOTAL_STEPS:4d}] "

        # Wrap the prefix in green
        green_prefix = f"\033[32m{progress_prefix}\033[0m"

        # Create the final message string like Python's built-in print()
        original_message = sep.join(str(arg) for arg in args)
        message = green_prefix + original_message + end

        # Print directly to the console
        try:
            sys.stdout.flush()
            print(message, end="")
        except UnicodeEncodeError:
            # Fallback: encode to ASCII and replace problematic characters
            try:
                ascii_message = message.encode('ascii', errors='replace').decode('ascii')
                print(ascii_message, end="")
            except Exception:
                # Final fallback: just print a simple message
                print(f"[PROGRESS:{progress_percent:3d}%] [Log message with encoding issues - {len(original_message)} chars]", end="")
        
        # Add a timestamped log entry to in-memory log buffer (without progress prefix for log file)
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        _TESTFLOW_LOGS.append(f"{original_message.strip()}")
     

    def log_print_panner(*args, sep=" ", end="\n"):
        """
        Prints to terminal and logs the same message for later saving.
        Now includes progress information at the beginning of each line.
        """
        # Calculate progress percentage
        progress_percent = 0
        if _TOTAL_STEPS > 0:
            progress_percent = min(int((_CURRENT_STEP / _TOTAL_STEPS) * 100), 100)
        
        # Create progress prefix
        progress_prefix = ""
        
        # Create the final message string like Python's built-in print()
        original_message = sep.join(str(arg) for arg in args)
        message = progress_prefix + original_message + end

        # Print directly to the console with encoding handling
        try:
            sys.stdout.flush()
            print(message, end="")
        except UnicodeEncodeError:
            # Fallback: encode to ASCII and replace problematic characters
            try:
                ascii_message = message.encode('ascii', errors='replace').decode('ascii')
                print(ascii_message, end="")
            except Exception:
                # Final fallback: just print a simple message
                print(f"[PROGRESS:{progress_percent:3d}%] [Log message with encoding issues - {len(original_message)} chars]", end="")
        
        # Add a timestamped log entry to in-memory log buffer (without progress prefix for log file)
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        _TESTFLOW_LOGS.append(f"{original_message.strip()}") 

    def save_all_logs(file_path: str):
        """
        Saves all collected logs to a file at the end of execution.
        """
        try:
            # If there are no logs collected, print info and return.
            if not _TESTFLOW_LOGS:
                log_print("[INFO] No logs to save.")
                return

            # Ensure the directory for the log file exists.
            os.makedirs(os.path.dirname(file_path), exist_ok=True)

            # Open the log file in append mode and write all logs as lines.
            with open(file_path, "a", encoding="utf-8") as f:
                f.write("\n".join(_TESTFLOW_LOGS) + "\n")

            # Inform user of successful log save and clear the log list.
            log_print(f"[INFO] All logs saved to: {file_path}")
            #_TESTFLOW_LOGS.clear()

        except Exception as e:
            # If any error occurs during log saving, print error message.
            log_print(f"\033[31m[ERROR] Failed to save logs: {e}\033[0m")


    def send_to_read_byte(visa_address: str, query: str):
        """
        Sends a SCPI query to the instrument at `visa_address` and returns the reply.
        If expecting binary data (e.g., image), returns bytes.
        """
        import pyvisa
        try:
            rm = pyvisa.ResourceManager()
            instrument = rm.open_resource(visa_address)
            # For binary image queries
            instrument.write(query)
            reply = instrument.read_raw()  # This returns bytes, not string!
            instrument.close()
            return reply  # This is bytes (for image data)
        except Exception as e:
            log_print(f"\033[31mTestFlow says Error: {e}\033[0m")
            return None
            


    def create_unique_image_file(path, image_name):
        # Ensure the directory exists
        os.makedirs(path, exist_ok=True)
        
        # Start with the original name
        base_name = image_name
        ext = ".png"
        full_name = base_name + ext
        full_path = os.path.join(path, full_name)
        
        counter = 1
        # Loop until we find a non-existing filename
        while os.path.exists(full_path):
            full_name = f"{base_name}({counter}){ext}"
            full_path = os.path.join(path, full_name)
            counter += 1

        # Actually create the file (as empty for now)
        with open(full_path, 'wb') as f:
            pass  # You can write image data here if needed

        return full_path

    def create_unique_set_file(path, image_name):
        # Ensure the directory exists
        os.makedirs(path, exist_ok=True)
        
        # Start with the original name
        base_name = image_name
        ext = ".set"
        full_name = base_name + ext
        full_path = os.path.join(path, full_name)
        
        counter = 1
        # Loop until we find a non-existing filename
        while os.path.exists(full_path):
            full_name = f"{base_name}({counter}){ext}"
            full_path = os.path.join(path, full_name)
            counter += 1

        # Actually create the file (as empty for now)
        with open(full_path, 'wb') as f:
            pass  # You can write image data here if needed

        return full_path


    def save_image_data(image_path, image_data):
        """
        Saves binary image data to the specified file path.

        Args:
            image_path (str): Full file path where the image will be saved.
            image_data (bytes): Binary image data to save.
        """
        with open(image_path, 'wb') as f:
            f.write(image_data)




    def show_message_dialog(title, message):
        #root = tk.Tk()
        #root.withdraw()  # Hide the main window
        #messagebox.showinfo(title, message)
        #root.destroy()
        input("Press Enter to continue...")


    def read_and_delete_paths_file(filename: str):
        """
        Reads script_path and output_path from a file, validates, deletes the file.
        Returns (script_path, output_path).
        Raises FileNotFoundError or ValueError on error.
        """
        if not os.path.exists(filename):
            raise FileNotFoundError(f"Paths file does not exist: {filename}")

        with open(filename, 'r', encoding='utf-8') as f:
            lines = [line.strip() for line in f if line.strip()]

        if len(lines) < 2:
            raise ValueError("Paths file is invalid or incomplete")

        script_path, output_path = lines[0], lines[1]

        # Validate script_path exists
        if not os.path.exists(script_path):
            raise FileNotFoundError(f"Script path does not exist: {script_path}")

        # Validate output_path's directory exists
        output_dir = os.path.dirname(output_path)
        if output_dir and not os.path.exists(output_dir):
            raise FileNotFoundError(f"Output directory does not exist: {output_dir}")

        # Delete the paths file
        os.remove(filename)

        return script_path, output_path



    # ******************************************************************************************************************************* 
    # ******************************************************************************************************************************* 
    # ******************************************************************************************************************************* 
    # *******************************************************************************************************************************    


    def write_status(output_path, status):
        """
        Writes the current status (Running, Pause, Resume, Stop) to a status.txt file
        in the same folder as output_path. Auto-creates the directory if needed.
        """
        out_dir = os.path.dirname(os.path.abspath(output_path))
        os.makedirs(out_dir, exist_ok=True)  # Auto-create directory if missing
        status_file = os.path.join(out_dir, 'status.txt')

        with open(status_file, 'w', encoding='utf-8') as f:
            f.write(status)
            
        #log_print("[INFO] control file is ",status_file )



    # ******************************************************************************************************************************* 
    # ******************************************************************************************************************************* 
    # ******************************************************************************************************************************* 
    # *******************************************************************************************************************************    

    def check_status_file(output_path: str) -> str:
        """Check the status.txt file for execution control commands."""
        try:
            status_file = os.path.join(output_path, 'status.txt')
            if os.path.exists(status_file):
                with open(status_file, 'r') as f:
                    status = f.read().strip().lower()
                return status
            return 'running'  # Default status if file doesn't exist
        except Exception as e:
            log_print(f"\033[31mError reading status file: {e}\033[0m")
            return 'running'

    def wait_while_paused(output_path: str):
        """Wait while the script is paused, checking status periodically."""
        while True:
            status = check_status_file(output_path)

            # Case 1: Resume the script
            if status == 'resume':
                try:
                    status_file = os.path.join(output_path, 'status.txt')
                    with open(status_file, 'w') as f:
                        f.write('Running')
                except Exception as e:
                    log_print(f"\033[31mError updating status file: {e}\033[0m")
                break

            # Case 2: Script is already running → break immediately
            elif status == 'Running':
                break

            # Case 3: Stop execution
            elif status == 'stop':
                log_print("Script execution stopped by user")
                sys.exit(0)

            # Otherwise (pause or anything else) → wait and check again
            time.sleep(1)



    def delete_status_file(output_path):
        """
        Deletes the status.txt file in the same directory as output_path.
        Does nothing if the file does not exist.
        """
        #out_dir = os.path.dirname(os.path.abspath(output_path))
        status_file = os.path.join(output_path, 'status.txt')
        try:
            if os.path.exists(status_file):
                os.remove(status_file)
                
        except Exception as e:
            log_print(f"\033[31mError deleting status file: {e}\033[0m")



    def parse_script_structured_v6(path, case_sensitive=True):
        text = Path(path).read_text(encoding="utf-8", errors="replace")
        lines = text.splitlines()

        def norm(s): return s if case_sensitive else s.lower()
        nlines = [norm(L) for L in lines]

        START = norm("#START_SCRIPT")
        END   = norm("#END_SCRIPT")
        WF    = norm("#START_WORKFLOW")  # ← NEW

        # Find START_SCRIPT
        start_idx = next((i for i, L in enumerate(nlines, start=1) if START in L), None)
        if start_idx is None:
            return {"_ERROR": "START_SCRIPT not found"}

        # Find END_SCRIPT after START_SCRIPT
        end_idx = next(
            (i for i in range(start_idx, len(nlines) + 1) if END in nlines[i - 1]),
            None
        )

        # Fallback: if END_SCRIPT not found, use first START_WORKFLOW as boundary
        if end_idx is None:
            wf_idx = next(
                (i for i in range(start_idx, len(nlines) + 1) if WF in nlines[i - 1]),
                None
            )
            if wf_idx is None:
                return {
                    "_ERROR": "END_SCRIPT not found (after START_SCRIPT) and no START_WORKFLOW found"
                }
            # Use the line before #START_WORKFLOW as the script end (exclude the workflow line)
            end_idx = wf_idx - 1
            if end_idx < start_idx:
                return {
                    "_ERROR": "START_WORKFLOW found before START_SCRIPT; cannot determine script window"
                }

        flags = 0 if case_sensitive else re.IGNORECASE
        re_node_start = re.compile(r"#NODE\s*(\d+)\b(?!_IF)", flags)
        re_node_end   = re.compile(r"#END_NODE\s*(\d+)\b", flags)
        re_loop_start = re.compile(r"Loop_start\s*\(\s*(\d+)\s*\)", flags)
        re_loop_end   = re.compile(r"Loop_end\s*\(\s*(\d+)\s*\)", flags)

        re_node_if_start = re.compile(r"#NODE\s*(\d+)_IF\s*\((.*?)\)\s*$", flags)
        re_end_if        = re.compile(r"#END_IF\b", flags)
        re_true_line     = re.compile(r"^\s*TRUE\s*:\s*(N|LE)\s*(\d+)\s*$", flags)
        re_false_line    = re.compile(r"^\s*FALSE\s*:\s*(N|LE)\s*(\d+)\s*$", flags)

        re_next_after_endnode = re.compile(r"#END_NODE\s*(\d+).*?\(\s*(N|LE)\s*(\d+)\s*\)", flags)
        re_loop_start_full    = re.compile(r"Loop_start\s*\(\s*(\d+)\s*\)\s*:\s*(\d+)\s*\(\s*N\s*(\d+)\s*\)", flags)

        script_markers = {"#START_SCRIPT": [], "#START_WORKFLOW": [], "#END_WORKFLOW": [], "#END_SCRIPT": []}
        nodes, loops = {}, {}
        node_all_starts, node_all_ends = {}, {}
        loop_all_starts, loop_all_ends = {}, {}
        refs = []  # (kind, src_id, ref_type, ref_id, source_line, branch)

        in_if = False
        if_id = if_equ = None
        if_start_line = None
        if_true_src, if_false_src = None, None
        if_next_true = if_next_false = None

        for lineno in range(start_idx, end_idx + 1):
            raw = lines[lineno-1]
            L   = nlines[lineno-1]

            if START in L: script_markers["#START_SCRIPT"].append(lineno)
            if WF in L:    script_markers["#START_WORKFLOW"].append(lineno)
            if norm("#END_WORKFLOW") in L: script_markers["#END_WORKFLOW"].append(lineno)
            if END in L:   script_markers["#END_SCRIPT"].append(lineno)

            # Inside IF node body
            if in_if:
                mt = re_true_line.search(raw if case_sensitive else L)
                if mt:
                    if_next_true = (mt.group(1), mt.group(2))
                    if_true_src = lineno
                    continue
                mf = re_false_line.search(raw if case_sensitive else L)
                if mf:
                    if_next_false = (mf.group(1), mf.group(2))
                    if_false_src = lineno
                    continue
                me = re_end_if.search(raw if case_sensitive else L)
                if me:
                    nodes.setdefault(if_id, {})
                    nodes[if_id]["type"] = "IF"
                    nodes[if_id]["equation"] = if_equ
                    if "start" not in nodes[if_id]:
                        nodes[if_id]["start"] = if_start_line
                    nodes[if_id]["end"] = lineno
                    if if_next_true is not None:
                        rtype, rid = if_next_true
                        nodes[if_id]["true"] = {"type": rtype, "id": rid}
                        refs.append(("NODE_IF_TRUE", if_id, rtype, rid, if_true_src, "TRUE"))
                    if if_next_false is not None:
                        rtype, rid = if_next_false
                        nodes[if_id]["false"] = {"type": rtype, "id": rid}
                        refs.append(("NODE_IF_FALSE", if_id, rtype, rid, if_false_src, "FALSE"))
                    in_if = False
                    if_id = if_equ = if_start_line = None
                    if_true_src = if_false_src = None
                    if_next_true = if_next_false = None
                    continue
                continue

            # IF node start
            mif = re_node_if_start.search(raw if case_sensitive else L)
            if mif:
                if_id = mif.group(1)
                if_equ = mif.group(2).strip()
                if_start_line = lineno
                in_if = True
                nodes.setdefault(if_id, {})
                if "start" not in nodes[if_id]:
                    nodes[if_id]["start"] = if_start_line
                node_all_starts.setdefault(if_id, []).append(if_start_line)
                continue

            # Standard node start
            m = re_node_start.search(raw if case_sensitive else L)
            if m:
                nid = m.group(1)
                nodes.setdefault(nid, {})
                nodes[nid].setdefault("type", "N")
                if "start" not in nodes[nid]:
                    nodes[nid]["start"] = lineno
                node_all_starts.setdefault(nid, []).append(lineno)

            # Standard node end
            m = re_node_end.search(raw if case_sensitive else L)
            if m:
                nid = m.group(1)
                nodes.setdefault(nid, {})
                nodes[nid].setdefault("type", "NODE")
                nodes[nid]["end"] = lineno
                node_all_ends.setdefault(nid, []).append(lineno)
                mnext = re_next_after_endnode.search(raw if case_sensitive else L)
                if mnext:
                    rtype, rid = mnext.group(2), mnext.group(3)
                    nodes[nid]["next"] = {"type": rtype, "id": rid}
                    refs.append(("NODE", nid, rtype, rid, lineno, None))

            # Loop start (full)
            mfull = re_loop_start_full.search(raw if case_sensitive else L)
            if mfull:
                lid, iters, nextn = mfull.group(1), mfull.group(2), mfull.group(3)
                loops.setdefault(lid, {})
                if "start" not in loops[lid]:
                    loops[lid]["start"] = lineno
                loops[lid].setdefault("current_iteration", 1)
                loops[lid]["type"] = "loop"
                loops[lid]["iterations"] = int(iters)
                loops[lid]["next"] = {"type": "N", "id": nextn}
                refs.append(("LOOP_START", lid, "N", nextn, lineno, None))
                loop_all_starts.setdefault(lid, []).append(lineno)
            else:
                # Loop start (basic)
                mbase = re_loop_start.search(raw if case_sensitive else L)
                if mbase:
                    lid = mbase.group(1)
                    loops.setdefault(lid, {})
                    if "start" not in loops[lid]:
                        loops[lid]["start"] = lineno
                    loops[lid].setdefault("current_iteration", 0)
                    loops[lid].setdefault("type", "loop")
                    mnext = re.search(r"\(\s*N\s*(\d+)\s*\)", raw if case_sensitive else L, flags)
                    if mnext:
                        nextn = mnext.group(1)
                        loops[lid]["next"] = {"type": "N", "id": nextn}
                        refs.append(("LOOP_START", lid, "N", nextn, lineno, None))
                    loop_all_starts.setdefault(lid, []).append(lineno)

            # Loop end
            m = re_loop_end.search(raw if case_sensitive else L)
            if m:
                lid = m.group(1)
                loops.setdefault(lid, {})
                loops[lid].setdefault("type", "loop")
                loops[lid]["end"] = lineno
                loop_all_ends.setdefault(lid, []).append(lineno)

        # Resolve references
        warnings = []
        for kind, src_id, rtype, rid, source_line, branch in refs:
            dest_line = None
            if rtype == "N":
                dest_line = nodes.get(rid, {}).get("start")
                if dest_line is None:
                    warnings.append(f"Ref at line {source_line}: N{rid} not found or has no start.")
            elif rtype == "LE":
                dest_line = loops.get(rid, {}).get("end")
                if dest_line is None:
                    warnings.append(f"Ref at line {source_line}: LE{rid} not found or has no end.")

            if kind == "NODE" and "next" in nodes.get(src_id, {}):
                nodes[src_id]["next"]["line"] = dest_line if dest_line is not None else source_line
                nodes[src_id]["next"]["source_line"] = source_line
            elif kind == "LOOP_START" and "next" in loops.get(src_id, {}):
                loops[src_id]["next"]["line"] = dest_line if dest_line is not None else source_line
                loops[src_id]["next"]["source_line"] = source_line
            elif kind == "NODE_IF_TRUE" and "true" in nodes.get(src_id, {}):
                nodes[src_id]["true"]["line"] = dest_line if dest_line is not None else source_line
                nodes[src_id]["true"]["source_line"] = source_line
            elif kind == "NODE_IF_FALSE" and "false" in nodes.get(src_id, {}):
                nodes[src_id]["false"]["line"] = dest_line if dest_line is not None else source_line

        # Default next for standard nodes with no explicit next
        for nid, rec in nodes.items():
            if rec.get("type") == "IF":
                continue
            if "end" in rec and "next" not in rec:
                fallback_line = rec["end"] + 1 if rec["end"] < end_idx else None
                rec["next"] = {
                    "type": "X",
                    "id": "X",
                    "line": fallback_line,
                    "source_line": rec["end"]
                }

        return {
            "window": {"start_line": start_idx, "end_line": end_idx},
            "script_markers": script_markers,
            "nodes": nodes,
            "loops": loops,
            "warnings": warnings
        }


    def classify_script_line_at(
        script_path: str,
        line_number: int,
        include_next: bool = False,
        case_sensitive: bool = False
    ) -> Optional[Dict[str, Any]]:
        """
        Classify a single script line by (path, 1-based line number).

        Recognized forms:
          - '#NODE<id> (<...>)'                 -> type='N', which='START'
          - '#END_NODE<id> (<N<k>|LE<k>>)'      -> type='N', which='END', next=...
          - '#NODE<id>_IF (<equation>)'         -> type='IF'
          - 'Loop_start(<id>): <iters> (N<k>)'  -> type='LOOP_START', next=...
          - 'Loop_end(<id>)'                    -> type='LOOP_END'

        Returns dict or None if the line does not match.
        """

        # Compile regexes with chosen case sensitivity
        flags = 0 if case_sensitive else re.IGNORECASE

        NODE_START_RE = re.compile(r"^\s*#NODE\s*(\d+)\b\s*(?:\([^)]*\))?\s*$", flags)
        NODE_END_RE   = re.compile(r"^\s*#END_NODE\s*(\d+)\b(?:.*?\(\s*(N|LE)\s*(\d+)\s*\))?\s*$", flags)
        NODE_IF_RE    = re.compile(r"^\s*#NODE\s*(\d+)_IF\s*\((.*?)\)\s*$", flags)
        LOOP_START_RE = re.compile(r"^\s*Loop_start\s*\(\s*(\d+)\s*\)\s*:\s*(\d+)\s*(?:\(\s*N\s*(\d+)\s*\))?\s*$", flags)
        LOOP_END_RE   = re.compile(r"^\s*Loop_end\s*\(\s*(\d+)\s*\)\s*$", flags)

        # Load the requested line (1-based)
        p = Path(script_path)
        if not p.exists():
            raise FileNotFoundError(f"Script not found: {script_path}")
        lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
        if line_number < 1 or line_number > len(lines):
            raise IndexError(f"line_number out of range: 1..{len(lines)}")

        s = lines[line_number - 1].rstrip("\n")

        # IF node
        m = NODE_IF_RE.match(s)
        if m:
            return {"type": "IF", "number": m.group(1)}

        # Node start
        m = NODE_START_RE.match(s)
        if m:
            return {"type": "N", "which": "START", "number": m.group(1)}

        # Node end
        m = NODE_END_RE.match(s)
        if m:
            out = {"type": "N", "which": "END", "number": m.group(1)}
            if include_next and m.group(2) and m.group(3):
                out["next"] = {"type": m.group(2).upper(), "id": m.group(3)}
            return out

        # Loop start
        m = LOOP_START_RE.match(s)
        if m:
            out = {"type": "LOOP_START", "number": m.group(1)}
            if include_next and m.group(3):
                out["next"] = {"type": "N", "id": m.group(3)}
            return out

        # Loop end
        m = LOOP_END_RE.match(s)
        if m:
            return {"type": "LOOP_END", "number": m.group(1)}

        # No match
        return None

    # --- Examples ---
    # classify_script_line_at("/path/to/script.atoms", 12, include_next=True)
    # classify_script_line_at("/path/to/script.atoms", 34)  # case-insensitive by default


    def write_status(output_path, status):
        """
        Writes the current status (Running, Pause, Resume, Stop) to a status.txt file
        in the same folder as output_path. Auto-creates the directory if needed.
        """
        out_dir = os.path.dirname(os.path.abspath(output_path))
        os.makedirs(out_dir, exist_ok=True)  # Auto-create directory if missing
        status_file = os.path.join(out_dir, 'status.txt')

        with open(status_file, 'w', encoding='utf-8') as f:
            f.write(status)
            
        #log_print ("[INFO] control file is ",status_file )



    def get_next_from_loop_end_line(line: str, case_sensitive: bool = False) -> Optional[Dict[str, Any]]:
        """
        Parse a line like:
          'Loop_end(1) (LE2)'
          'Loop_end(2) (N2)'
        and return:
          {'loop_end_id': '1', 'next': {'type': 'LE', 'id': '2'}}
        or None if it doesn't match.
        """
        flags = 0 if case_sensitive else re.IGNORECASE
        rx = re.compile(r"Loop_end\s*\(\s*(\d+)\s*\)\s*\(\s*(N|LE)\s*(\d+)\s*\)", flags)
        m = rx.search(line)
        if not m:
            return "X"
        loop_end_id, ntype, nid = m.group(1), m.group(2).upper(), m.group(3)
        return {"loop_end_id": loop_end_id, "next": {"type": ntype, "id": nid}}




    _allowed_binops = {
        ast.Add: operator.add,
        ast.Sub: operator.sub,
        ast.Mult: operator.mul,
        ast.Div: operator.truediv,
        ast.Pow: operator.pow,
        ast.Mod: operator.mod,
        ast.FloorDiv: operator.floordiv,
    }

    _allowed_unaryops = {
        ast.UAdd: operator.pos,
        ast.USub: operator.neg,
        ast.Not: operator.not_,
    }

    _allowed_boolops = {
        ast.And: lambda values: all(values),
        ast.Or:  lambda values: any(values),
    }

    _allowed_compares = {
        ast.Eq: operator.eq,
        ast.NotEq: operator.ne,
        ast.Gt: operator.gt,
        ast.Lt: operator.lt,
        ast.GtE: operator.ge,
        ast.LtE: operator.le,
    }

    def safe_eval_bool(expr: str) -> bool:
        """
        Safely evaluate expr and return True/False.
        - Returns False on any error or unsupported expression.
        - Allowed: numbers, binary math ops, comparisons, boolean ops (and/or), unary + - not.
        Examples:
          safe_eval_bool("25.5*2 > 65")  -> False
          safe_eval_bool("5 + 3")        -> True  (non-zero -> True)
          safe_eval_bool("0")            -> False
          safe_eval_bool("2 == 2 and 3>1")-> True
        """
        try:
            node = ast.parse(expr, mode="eval")
        except Exception:
            return False

        def _eval(n):
            # Expression wrapper
            if isinstance(n, ast.Expression):
                return _eval(n.body)

            # Numeric / constant literals
            if isinstance(n, ast.Constant):  # Python 3.8+
                val = n.value
                if isinstance(val, (int, float, bool)):
                    return val
                # disallow strings, bytes, None, etc.
                raise ValueError("Unsupported constant type")

            # New style (Python 3.8+): everything is ast.Constant
            if isinstance(n, ast.Constant):
                # n.value holds the actual Python object: int, float, str, bool, None, etc.
                return n.value

            # Optional: compatibility branches for very old ASTs (if you ever parse code
            # generated by older Python, or you're running this on 3.7 or below).
            if isinstance(n, ast.Num):  # pragma: no cover
                return n.n
            if isinstance(n, ast.NameConstant):  # pragma: no cover
                return n.value

            raise ValueError(f"Unsupported literal node: {type(n).__name__}")

            # Binary operations: +, -, *, /, **, %, //
            if isinstance(n, ast.BinOp):
                op_type = type(n.op)
                if op_type not in _allowed_binops:
                    raise ValueError("Unsupported binary operator")
                left = _eval(n.left)
                right = _eval(n.right)
                return _allowed_binops[op_type](left, right)

            # Unary operations: +x, -x, not x
            if isinstance(n, ast.UnaryOp):
                op_type = type(n.op)
                if op_type not in _allowed_unaryops:
                    raise ValueError("Unsupported unary operator")
                operand = _eval(n.operand)
                return _allowed_unaryops[op_type](operand)

            # Boolean operations: and / or
            if isinstance(n, ast.BoolOp):
                op_type = type(n.op)
                if op_type not in _allowed_boolops:
                    raise ValueError("Unsupported boolean operator")
                values = [_eval(v) for v in n.values]
                # boolean ops expect truthiness of each element
                return _allowed_boolops[op_type]([bool(v) for v in values])

            # Comparisons: a < b <= c etc.
            if isinstance(n, ast.Compare):
                left = _eval(n.left)
                for op, comparator in zip(n.ops, n.comparators):
                    op_type = type(op)
                    if op_type not in _allowed_compares:
                        raise ValueError("Unsupported comparison operator")
                    right = _eval(comparator)
                    if not _allowed_compares[op_type](left, right):
                        return False
                    left = right
                return True

            # Anything else is not allowed (calls, names, attributes, subscripts, comprehensions, etc.)
            raise ValueError("Unsupported expression node: " + n.__class__.__name__)

        try:
            value = _eval(node)
            # Convert final result to boolean explicitly:
            return bool(value)
        except Exception:
            return False

    def extract_equation(text: str) -> str | None:
        pattern = r"#NODE\d+_IF\s*\((.*)\)$"
        match = re.match(pattern, text.strip())
        if not match:
            return None
        return match.group(1).strip()



    def parse_workflows_from_script(path: str, case_sensitive: bool = True) -> Dict[str, Any]:
        """
        Parse a file and extract workflow blocks delimited by:
            #START_WORKFLOW(<workflow name>)
            ...
            #END_WORKFLOW(<workflow name>)

        Returns a dict with:
        {
          "workflows": { "<name>": [ { "start_line": int, "end_line": int,
                                       "lines": List[str], "content": str }, ... ] },
          "markers": { "#START_WORKFLOW": [line_numbers], "#END_WORKFLOW": [line_numbers] },
          "warnings": [ ... unmatched or other warnings ... ],
          "file_lines": total_lines_int
        }

        If multiple workflows share the same name, the value for that name is a list of objects
        (one per occurrence).
        """
        text = Path(path).read_text(encoding="utf-8", errors="replace")
        lines = text.splitlines()
        total_lines = len(lines)

        flags = 0 if case_sensitive else re.IGNORECASE
        re_start = re.compile(r"#START_WORKFLOW\s*\(\s*(.*?)\s*\)\s*$", flags)
        re_end   = re.compile(r"#END_WORKFLOW\s*\(\s*(.*?)\s*\)\s*$", flags)

        markers = {"#START_WORKFLOW": [], "#END_WORKFLOW": []}
        workflows: Dict[str, List[Dict[str, Any]]] = {}
        warnings: List[str] = []

        lineno = 0
        while lineno < total_lines:
            lineno += 1
            raw = lines[lineno - 1]

            m_start = re_start.search(raw)
            if m_start:
                name = m_start.group(1).strip()
                markers["#START_WORKFLOW"].append(lineno)

                # search for matching END_WORKFLOW(name) after this line
                end_line = None
                search_idx = lineno
                while search_idx < total_lines:
                    search_idx += 1
                    candidate = lines[search_idx - 1]
                    m_end = re_end.search(candidate)
                    if m_end:
                        end_name = m_end.group(1).strip()
                        # match names using case_sensitive semantics
                        if (name == end_name) if case_sensitive else (name.lower() == end_name.lower()):
                            end_line = search_idx
                            markers["#END_WORKFLOW"].append(end_line)
                            break

                if end_line is None:
                    warnings.append(f"START_WORKFLOW at line {lineno}: matching END_WORKFLOW({name}) not found.")
                    # Move on (no block captured), continue scanning after start line
                    continue

                # capture block content between start and end (exclusive)
                content_lines = lines[lineno: end_line - 1]  # start+1 .. end-1 (1-indexed)
                content = "\n".join(content_lines)

                # store workflow object (support multiple occurrences of same name)
                workflows.setdefault(name, []).append({
                    "start_line": lineno,
                    "end_line": end_line,
                    "lines": content_lines,
                    "content": content
                })

                # advance lineno to end_line so outer loop continues after the end marker
                lineno = end_line

            else:
                # check for stray END_WORKFLOW without prior START
                m_end_only = re_end.search(raw)
                if m_end_only:
                    end_name = m_end_only.group(1).strip()
                    markers["#END_WORKFLOW"].append(lineno)
                    warnings.append(f"END_WORKFLOW({end_name}) at line {lineno} has no matching START_WORKFLOW before it.")
                # continue scanning
                continue

        return {
            "workflows": workflows,
            "markers": markers,
            "warnings": warnings,
            "file_lines": total_lines
        }

    # -----------------------
    # Example usage:
    # result = parse_workflows_from_script("my_script.atoms", case_sensitive=False)
    # for wf_name, instances in result["workflows"].items():
    #     for idx, wf in enumerate(instances, start=1):
    #         print(f"Workflow {wf_name} (instance {idx}): lines {wf['start_line']}..{wf['end_line']}")
    #         print("Content preview:", wf['content'][:200])
    # print("Warnings:", result["warnings"])

        
    def insert_end_script(path, output_path=None,
                                                marker_prefix="#START_WORKFLOW",
                                                insert_line="#END_SCRIPT"):
        """
        Reads a text file and:
          - If a line starting with '#START_WORKFLOW' exists:
                inserts '#END_SCRIPT' before its first occurrence (if not already there).
          - If no such line exists:
                appends '#END_SCRIPT' at the end of the file (if not already there).

        - path: input file path
        - output_path: output file path (if None, overwrite the input file)
        """
        # Read all lines
        with open(path, "r", encoding="utf-8") as f:
            lines = f.read().splitlines()  # no trailing '\n' per line

        found_start = False

        # Look for first '#START_WORKFLOW'
        for idx, line in enumerate(lines):
            if line.lstrip().startswith(marker_prefix):
                found_start = True
                # Only insert if previous line is not already '#END_SCRIPT'
                if idx == 0 or lines[idx - 1].strip() != insert_line:
                    lines.insert(idx, insert_line)
                break  # only act on the first occurrence

        # If no '#START_WORKFLOW' found → append '#END_SCRIPT' at the end
        if not found_start:
            if not lines or lines[-1].strip() != insert_line:
                lines.append(insert_line)

        # Decide where to write
        if output_path is None:
            output_path = path  # overwrite original file

        # Write result
        with open(output_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")

        return output_path

        

    def create_subworkflow(lines, output_path):
        """
        Saves a list of text lines into a .txt file.

        lines: list of strings
        output_path: full path of the output file (e.g., 'led_test_output.txt')
        """
        with open(output_path, "w", encoding="utf-8") as f:
            f.write("#START_SCRIPT\n")
            for line in lines:
                f.write(line + "\n")
                
        insert_end_script(output_path)


    def extract_workflow_name(line):
        """
        Extracts the workflow name from a line like:
          'Work_flow:(LED_test)'
          'Work_flow:(LED_test):'
          '  Work_flow:( MyFlow )  '
        Returns the name as a string, or None if not found.
        """
        pattern = r"Work_flow:\(\s*(.+?)\s*\)"
        match = re.search(pattern, line)
        if match:
            return match.group(1)
        return None


    # *******************************************************************************************************************************
    def run_another_workflow(sub_script_location: str, sub_output_location: str, temp_csv= False):
        tempfile= run_script_new(sub_script_location, sub_output_location,True)
        log_print("Ended a workflow, file is =", tempfile)
        return tempfile



    def concat_csv_into_second(first_csv, second_csv, skip_header_first=False):
        """
        Concatenate rows from first_csv into second_csv.
        The output (merged) file is second_csv (modified in place).

        - first_csv: path to first CSV file
        - second_csv: path to second CSV file (will be modified)
        - skip_header_first: skip header row of first CSV

        After concatenation, this function:
          - appends all rows from first_csv into second_csv
          - then appends a row with '**' in the first column
          - then appends the header row of second_csv again

        RETURNS: total number of rows in the final second_csv file.
        """
        # ---------------------------------------------------------
        # 1) Read the header (and content) of the second CSV
        # ---------------------------------------------------------
        with open(second_csv, "r", encoding="utf-8", newline="") as f2_read:
            reader2 = csv.reader(f2_read)
            rows2_original = list(reader2)

        if not rows2_original:
            raise ValueError("Second CSV is empty — cannot copy header.")

        header_row = rows2_original[0]
        num_cols = len(header_row) if header_row else 1

        # ---------------------------------------------------------
        # 2) Load rows from first CSV
        # ---------------------------------------------------------
        with open(first_csv, "r", encoding="utf-8", newline="") as f1:
            reader1 = csv.reader(f1)
            rows_to_add = list(reader1)

        if skip_header_first and rows_to_add:
            rows_to_add = rows_to_add[1:]

        # ---------------------------------------------------------
        # 3) Append rows + '**' row + header at the end
        # ---------------------------------------------------------
        with open(second_csv, "a", encoding="utf-8", newline="") as f2_append:
            writer = csv.writer(f2_append)

            # Add rows from first CSV
            if rows_to_add:
                writer.writerows(rows_to_add)

            # Add separator row: '**' in first column, rest empty
            star_row = ["*************************************************************** Sub_script ended ***************************************************************"] + [""] * (num_cols - 1)
            writer.writerow(star_row)

            # Append second file header at the end
            writer.writerow(header_row)

        # ---------------------------------------------------------
        # 4) Count final number of rows
        # ---------------------------------------------------------
        with open(second_csv, "r", encoding="utf-8", newline="") as f_final:
            reader_final = csv.reader(f_final)
            final_rows = sum(1 for _ in reader_final)

        return final_rows


    def write_text_to_row_first_col(csv_path, row_index, text, encoding="utf-8"):
        """
        Writes `text` into the first column of row `row_index` in the CSV file.

        - If row_index is within range: update that row.
        - If row_index is beyond the last row: append empty rows until that index exists,
          then write text into the first column of that new row.

        Row index is 0-based (0 = first row).
        """
        # Read all rows
        with open(csv_path, "r", newline="", encoding=encoding) as f:
            reader = csv.reader(f)
            rows = list(reader)

        if row_index < 0:
            raise IndexError(f"Row index {row_index} cannot be negative.")

        # Determine column count for any new rows we may need to add
        if rows:
            num_cols = len(rows[0])
            if num_cols == 0:
                num_cols = 1
        else:
            # Empty CSV: start with at least 1 column
            num_cols = 1

        # If row_index is out of range, append empty rows until we reach it
        while len(rows) <= row_index:
            rows.append([""] * num_cols)

        # Now rows[row_index] definitely exists
        if not rows[row_index]:
            rows[row_index] = [""] * num_cols

        rows[row_index][0] = text

        # Write back to the same file
        with open(csv_path, "w", newline="", encoding=encoding) as f:
            writer = csv.writer(f)
            writer.writerows(rows)



    def delete_csv_file(file_path):
        """
        Deletes a CSV file from disk.

        - file_path: full path to the CSV file

        RETURNS:
            True  -> file successfully deleted
            False -> file does not exist
        """
        if not os.path.isfile(file_path):
            return False  # nothing to delete

        try:
            os.remove(file_path)
            return True
        except Exception as e:
            raise RuntimeError(f"Failed to delete file '{file_path}': {e}")


    def compute_loop_weight(script_path: str) -> int:
        """
        Compute:
            sum_over_loops( loop_iterations * nodes_inside_loop )

        If no loops are found, return the total number of nodes in the script.

        Input:
            script_path: path to the .atom script file

        Returns:
            Integer value:
                - If loops exist:
                    Loop1_iterations * Loop1_node_count
                  + Loop2_iterations * Loop2_node_count
                  + ...
                - If no loops:
                    total_node_count
        """
        text = Path(script_path).read_text(encoding="utf-8", errors="replace")
        lines = text.splitlines()

        # Regex patterns
        loop_start_re = re.compile(
            r'^\s*Loop_start\((\d+)\)\s*:\s*([0-9]+)\s*\(([^)]+)\)',
            re.IGNORECASE
        )
        loop_end_re = re.compile(
            r'^\s*Loop_end\((\d+)\)',
            re.IGNORECASE
        )
        # Matches "#NODE1", "#NODE2", "#NODE5_IF", etc.
        node_re = re.compile(
            r'^\s*#NODE(\d+)',
            re.IGNORECASE
        )

        loops = []              # list of dicts: { "iterations": int, "node_count": int }
        loop_stack = []         # stack of indices into `loops`
        total_node_count = 0    # global node count (used when no loops)

        for line_no, line in enumerate(lines, start=1):
            # Detect Loop_start
            m_start = loop_start_re.match(line)
            if m_start:
                iterations = int(m_start.group(2))

                loop_info = {
                    "iterations": iterations,
                    "node_count": 0,
                }
                loops.append(loop_info)
                loop_stack.append(len(loops) - 1)
                continue

            # Detect Loop_end
            m_end = loop_end_re.match(line)
            if m_end:
                if loop_stack:
                    loop_stack.pop()
                continue

            # Detect node lines
            m_node = node_re.match(line)
            if m_node:
                total_node_count += 1  # count all nodes globally
                # Count this node for all currently open loops
                for idx in loop_stack:
                    loops[idx]["node_count"] += 1
                continue

        # If no loops found, return total node count
        if not loops:
            return total_node_count

        # Otherwise: sum(iterations * node_count) over all loops
        total = 0
        for lp in loops:
            total += lp["iterations"] * lp["node_count"]

        return total



    def eval_expr_after_equal(line: str):
        """
        From a line like:
            'CMD: ${Var_1}=25*(12.35+0.235)/(2500)'
        extract the expression after '=' and evaluate it.

        On error: print an error message and exit the program.
        """
        try:
            # Make sure '=' exists
            if '=' not in line:
                print(f"\033[31m[ERROR] No '=' found in line: {line!r}\033[0m")
                sys.exit(1)

            # Take everything after the FIRST '='
            expr = line.split('=', 1)[1].strip()

            if not expr:
                print(f"\033[31m[ERROR] No expression found after '=' in line: {line!r}\033[0m")
                sys.exit(1)

            # Simple / unsafe eval: only if you trust the input!
            result = eval(expr)
            return result

        except SyntaxError as e:
            print(f"\033[31m[ERROR] Invalid expression syntax after '=': {e}\033[0m")
            sys.exit(1)

        except Exception as e:
            print(f"\033[31m[ERROR] Failed to evaluate expression after '=': {e}\033[0m")
            sys.exit(1)



    def extract_var_before_equal(line: str) -> str:
        """
        Extracts the variable name that appears between '${' and '}' 
        immediately before an '='.

        Examples:
            'CMD: ${Var_1}=25*(12.35+0.235)/(2500)'  -> 'Var_1'
            'CMD: ${out}=25*CMD: ${Var_1}=25*${Var_1}(...)' -> 'out'
        """
        # Look for pattern: ${...} followed by optional spaces then '='
        match = re.search(r'\$\{([^}]+)\}\s*=', line)
        if not match:
            print(f"\033[31m[ERROR] No variable of form '${{var}}=' found in line: {line!r}\033[0m")
            sys.exit(1)

        var_name = match.group(1).strip()
        if not var_name:
            print(f"\033[31m[ERROR] Empty variable name between '${{}}' before '=' in line: {line!r}\033[0m")
            sys.exit(1)

        return var_name

    def var2save_name(text: str) -> str:
        """
        Extract variable name from a string like '${Var_1}'.
        Returns the inner text (e.g., Var_1).
        Stops execution with error if format is invalid.
        """
        match = re.fullmatch(r'\s*\$\{([^}]+)\}\s*', text)
        if not match:
            print(f"\033[31m[ERROR] Invalid variable format (expected '${{var}}'): {text!r}\033[0m")
            sys.exit(1)

        return match.group(1).strip()
        
    def show_debug_message(title):
        input(title)
    def create_out_directory(output_location,dir_name):
        # Construct full path: <output_location>/out
        out_dir = os.path.join(output_location, dir_name)
        
        # Create directory (no error if it already exists)
        os.makedirs(out_dir, exist_ok=True)
        
        return out_dir
    
    def run_script_new(script_location: str, output_location: str, temp_csv: bool= False,debug_mode: bool=False):
        new_dir_name = Path(script_location).stem + "_" + datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        output_location=create_out_directory(output_location,new_dir_name)
        # Print a large TestFlow banner at the start of execution.
        if not temp_csv:
            print_big_testflow_banner()
            log_print("Starting a script using ", code_version)
            
        
        script_obj = parse_script_structured_v6(script_location)
        #print(json.dumps(script_obj, indent=2))
        workflows_obi = parse_workflows_from_script(script_location, case_sensitive=False)
        #print("*************workflows_obi*****************")
        #print(json.dumps(workflows_obi, indent=2))
        #print("*************first_workflow*****************")
        #first_workflow= workflows_obi["workflows"]["loop_test"][0]
        #print(json.dumps(first_workflow, indent=2))
        #print("**************workflow_lines****************")
        #workflow_lines= first_workflow.get(str("lines"))
        #print(json.dumps(workflow_lines, indent=2))
        
        #===================================================================================== Checking VISA addresses    
        #validate_visa_connections(script_location)
        #===================================================================================== Script lines, variables and loops
        
        
        current_line= read_line_from_script(script_location, 2)
        node_id = 1
        INST_VISA=""
        current_action=""
        write_status(f"{output_location}\status.txt","Running")
        status = check_status_file(output_location)
        #log_print("                File is ",status)
        # Create the CSV file for results, and extract header map.

        outpath,file_name, header_map= create_csv_file(output_location,script_location,temp_csv)
        # Analyze script to get proper step count based on loop structure
        #script_analysis = analyze_steps_and_time(script_location)
        script_n_of_lines = count_script_lines(script_location)
        print("******************************************************** Total steps ",compute_loop_weight(script_location))
        # Set up progress tracking with correct step calculation
        #set_total_steps(compute_loop_weight(script_location))
        #set_current_step(0)
        
        # Extract all variable arrays defined in the script.
        variables = get_all_variable_arrays(script_location,script_obj["window"].get(str("start_line"), {}),script_obj["window"].get(str("end_line"), {}))
        # Print first 10 values of each variable array.
        for name, var_info in variables.items():
            log_print(f"{name}: {var_info['values'][:10]} ... total: {len(var_info['values'])}")
        
        loops_current_iterations: dict[str,any]={}
        
        
        #===================================================================================== First node preparation   
        if check_line_prefix(current_line, "Loop_start"):
            #print("Set the obiect if first node is a loop")
            current_node = script_obj["loops"].get(str(node_id), {})
            next_node= current_node.get("next")
        else:
            current_node = script_obj["nodes"].get(str(node_id), {})   
            next_node= current_node.get("next")
            #log_print("*********************************************************This is a Node of type", current_node.get("type"))
            
        #log_print("[",(datetime.now().strftime("%Y-%m-%d %H:%M:%S")),"]: ","Node: ",node_id , "Starts at: ",current_node.get("start"), "Ends at: ",current_node.get("end"))
        #log_print("[",(datetime.now().strftime("%Y-%m-%d %H:%M:%S")),"]: ","Next Node: ",next_node.get("id") , "Starts at: ",next_node.get("line"))
        #log_print("--------------------------------------")
        #log_print("Start the script")
        Data_line=1
        running_script= True
        just_ended_loop= False
        action_count=0
        while(running_script):
            script_line= current_node.get("start")
            last_line= current_node.get("end")  
            # Check for pause/stop commands
            status = check_status_file(output_location) 
            if status == 'pause':
                log_print("[",(datetime.now().strftime("%Y-%m-%d %H:%M:%S")),"]: ","Script execution paused by user")
                wait_while_paused(output_location)
                log_print("[",(datetime.now().strftime("%Y-%m-%d %H:%M:%S")),"]: ","Script execution resumed")
            elif status == 'stop':
                log_print("[",(datetime.now().strftime("%Y-%m-%d %H:%M:%S")),"]: ","Script execution stopped by user")
                break        
            while script_line< last_line+1:
                #===================================================
                if current_node.get("type")=="IF":
                    #print("==========================================IFFFFFFFF node==========================================")
                    current_node = script_obj["nodes"].get(str(node_id), {})
                    Current_line=read_line_from_script(script_location, script_line)
                    equation = extract_equation(Current_line)
                    script_line=script_line+3
                    if has_variable(equation):
                        equation=replace_variables_with_current_values(equation,variables)
                    if safe_eval_bool(equation):
                        next_node= current_node.get("true")
                        log_print("[",(datetime.now().strftime("%Y-%m-%d %H:%M:%S")),"]: ","IF equation: ",extract_equation(Current_line)," = (", equation,")  ", " [TRUE] ==> ",next_node.get("type"),next_node.get("id"))
                    else:
                        next_node= current_node.get("false")
                        log_print("[",(datetime.now().strftime("%Y-%m-%d %H:%M:%S")),"]: ","IF equation: ",extract_equation(Current_line)," = (", equation,")  ", " [FALSE] ==> ",next_node.get("type"),next_node.get("id"))
                elif current_node.get("type")=="N":
                    #print("==========================================A standard node==========================================")
                    current_node = script_obj["nodes"].get(str(node_id), {})
                    next_node= current_node.get("next")
                else:
                    #print("==========================================Loooooop==========================================")
                    current_node = script_obj["loops"].get(str(node_id), {})
                    next_node= current_node.get("next")
                    
                #===================================================================================================================================================
                #===================================================================================================================================================
                #===================================================================================================================================================
                #===================================================================================================================================================    
                #================================================= Reading the line and executing it ===============================================================
                #===================================================================================================================================================
                #===================================================================================================================================================
                #===================================================================================================================================================
                
                #print("Doing node:  ",current_node.get("type"),node_id, "   Next is: ",next_node.get("type"),next_node.get("id"))
                Current_line=read_line_from_script(script_location, script_line)    
                
                if check_line_prefix(Current_line, "Loop_start"):
                    this_loop_n=node_id
                    this_loop_current_iteration= current_node.get("current_iteration")
                    this_loop_total_iteration= current_node.get("iterations")
                    current_node["current_iteration"] = int(current_node.get("current_iteration", 0))
                    if this_loop_current_iteration > this_loop_total_iteration:
                        loop_end_line= current_node.get("end") 
                        Current_line=read_line_from_script(script_location, loop_end_line) 
                        after_loop = get_next_from_loop_end_line(Current_line)
                        #print("After loop is ",after_loop)
                        log_print("[",(datetime.now().strftime("%Y-%m-%d %H:%M:%S")),"]: ","\033[32m████████████████████████████████████████████████\033[0m Loop ",node_id," ended", this_loop_total_iteration, " iterations")
                        if not after_loop== "X":
                            next_type = after_loop["next"]["type"]  
                            next_num  = int(after_loop["next"]["id"])
                            #print("next_num loop is ",next_num)
                            if next_type=="LE":
                              current_node = script_obj["loops"].get(str(next_num), {})
                              next_node["id"]= next_num
                            elif next_type=="N":
                                current_node = script_obj["nodes"].get(str(next_num), {})
                                next_node["id"]= next_num
                            else:
                                current_node = script_obj["nodes"].get(str(next_num), {})
                                next_node["id"]= next_num 
                                
                            just_ended_loop= True
                            log_print("----------------------------------------------------------------- Ended the loop, Next node is ", next_node, "current_node  ", current_node)
                            break
                        else:
                           running_script= False
                           break
                            
                    #log_print("======= LOOP ",this_loop_n," => Iteration= ",this_loop_current_iteration, " ======Next is: ",next_node.get("type"),next_node.get("id"),"=======")
                    log_print("[",(datetime.now().strftime("%Y-%m-%d %H:%M:%S")),"]: ","\033[33m████████████████████████ LOOP ",this_loop_n," => Iteration= ",this_loop_current_iteration,"████████████████████████\033[0m")
                    # Define open loop and update CSV.
                    loop_column_name=f"Loop({node_id})"
                    update_csv_cell(outpath,Data_line,"N",Data_line)
                    update_csv_cell(outpath,Data_line,loop_column_name,this_loop_current_iteration)
                elif check_line_prefix(Current_line, "Variable:"):
                    # When a variable line is found, update its current value for this iteration.
                    Var_name_is=extract_prefixed_line(Current_line, "Variable: ")
                    # Select next value for the variable array in the current iteration.
                    variables[Var_name_is]['current_value']=variables[Var_name_is]['values'][this_loop_current_iteration-1]
                    log_print("[",(datetime.now().strftime("%Y-%m-%d %H:%M:%S")),"]: ","[",Var_name_is,"] = ",variables[Var_name_is]['current_value'])
                    update_csv_cell(outpath,Data_line,Var_name_is,variables[Var_name_is]['current_value'])
                
                #elif check_line_prefix(Current_line, "Range:"):
                    # Log and skip range lines (no action taken).
                    #log_print("[",(datetime.now().strftime("%Y-%m-%d %H:%M:%S")),"]: ","....")
                
                elif check_line_prefix(Current_line, "#NODE"):
                    # Start of a node block. Parse node and log its info.
                    increment_step()
                    action_count=0
                    node_info=parse_node_line(Current_line)
                    log_print("[",(datetime.now().strftime("%Y-%m-%d %H:%M:%S")),"]: ","Node[", node_info['node_number'],"]   " ,node_info['node_type'],"   " ,node_info['instrument_name'],"   " ,node_info['manufacturer'])
                elif check_line_prefix(Current_line, "INST::"):
                    # Extract and set the instrument VISA address.
                    INST_VISA=extract_prefixed_line(Current_line, "INST:: ")
                    log_print("[",(datetime.now().strftime("%Y-%m-%d %H:%M:%S")),"]: ","    VISA Address (",INST_VISA,") [",node_info['node_type'],"]")            
                elif check_line_prefix(Current_line, "#ACTION:"):
                    # Start of an action block. Parse and log action.
                    action_count=action_count+1
                    current_action=get_action_title(Current_line)
                    log_print("[",(datetime.now().strftime("%Y-%m-%d %H:%M:%S")),"]:     [",action_count,"]Action: ", current_action)  
                    if current_action=="Math":
                        script_line=script_line+1
                        Current_line=read_line_from_script(script_location, script_line)
                        output_variable= extract_var_before_equal(Current_line)
                        equation=replace_variables_with_current_values(Current_line,variables)
                        variables[output_variable]['current_value']= eval_expr_after_equal(equation)
                        log_print("[",(datetime.now().strftime("%Y-%m-%d %H:%M:%S")),"]:     ",output_variable,"=",equation,"=",variables[output_variable]['current_value'])
       
                elif check_line_prefix(Current_line, "CMD:"):
                    # Process a command to be sent to instrument or execute local action.
                    command=extract_prefixed_line(Current_line, "CMD:")
                    # If command contains variables, replace with their values.
                    if has_variable(command):
                       command=replace_variables_with_current_values(command,variables)
                       #log_print("[",(datetime.now().strftime("%Y-%m-%d %H:%M:%S")),"]:     ",command)
                    # Check for wait command.
                    if check_line_prefix(command, "wait"):
                        # Delay/wait command.
                        log_print("[",(datetime.now().strftime("%Y-%m-%d %H:%M:%S")),"]: ","        Waiting for ",wait_time_is(command)," ms" )
                        time.sleep(wait_time_is(command)/1000)

                    elif has_question_mark(command):
                        # SCPI query (read data from instrument).
                        #log_print("[",(datetime.now().strftime("%Y-%m-%d %H:%M:%S")),"]: ","Send and recieve", command)
                        Measurment=send_scpi_query(INST_VISA, command)
                        time.sleep(80/1000)
                        # Update CSV with measurement result.
                        action_column_title = f"{current_action}(N{node_info['node_number']}|A{action_count})"
                        update_csv_cell(outpath,Data_line,action_column_title,Measurment)
                        write_flag=1
                        log_print("[",(datetime.now().strftime("%Y-%m-%d %H:%M:%S")),"]:     ",action_column_title," = ", Measurment)
                    elif check_line_prefix(command, "save2var"):
                        Varible2save= var2save_name(extract_prefixed_line(command, "CMD: save2var "))
                        variables[Varible2save]['current_value']=Measurment
                        log_print("[",(datetime.now().strftime("%Y-%m-%d %H:%M:%S")),"]:     ",Varible2save," = ", Measurment)
                    else:
                        # Generic SCPI command (write only, no read).
                        send_scpi_command(INST_VISA, command)
                        #log_print("[",(datetime.now().strftime("%Y-%m-%d %H:%M:%S")),"]: ","Command sent", current_action," , CMD: ",command)
                
                elif check_line_prefix(Current_line, "QRY:"):
                    command=extract_prefixed_line(Current_line, "QRY:")
                     # SCPI query (read data from instrument).
                    #log_print("[",(datetime.now().strftime("%Y-%m-%d %H:%M:%S")),"]: ","Send and recieve", command)
                    Measurment=send_scpi_query(INST_VISA, command)
                    time.sleep(80/1000)
                    # Update CSV with measurement result.
                    action_column_title = f"{current_action}(N{node_info['node_number']}|A{action_count})"
                    update_csv_cell(outpath,Data_line,action_column_title,Measurment)
                    write_flag=1
                    log_print("[",(datetime.now().strftime("%Y-%m-%d %H:%M:%S")),"]: ",action_column_title," = ", Measurment)
                    
                #elif check_line_prefix(Current_line, "MESSAGE:"):
                #    pause_message= extract_prefixed_line(Current_line, "MESSAGE:")
                #    show_message_dialog("Waiting you",pause_message)
                    
                elif check_line_prefix(Current_line, "PNG"):
                    command=extract_prefixed_line(Current_line, "PNG:")
                    image_name= f"image_{Data_line}"
                    image_path=create_unique_image_file(output_location,image_name)
                    image_data=send_to_read_byte(INST_VISA, command)
                    # Save the image data to file
                    save_image_data(image_path, image_data)
                    action_column_title = f"{current_action}img(N{node_info['node_number']}|A{action_count})"
                    update_csv_cell(outpath,Data_line,action_column_title,image_path)
                    
                elif check_line_prefix(Current_line, "SET"):
                    command=extract_prefixed_line(Current_line, "SET:")
                    image_name= f"image_{Data_line}"
                    image_path=create_unique_set_file(output_location,image_name)
                    image_data=send_to_read_byte(INST_VISA, command)
                    # Save the image data to file
                    save_image_data(image_path, image_data)
                    action_column_title = f"{current_action}set(N{node_info['node_number']}|A{action_count})"
                    update_csv_cell(outpath,Data_line,action_column_title,image_path)                    
                #elif check_line_prefix(Current_line, "#END_ACTION"):
                    # End of action block.
                    #log_print("[",(datetime.now().strftime("%Y-%m-%d %H:%M:%S")),"]: ","close action", current_action)
                    #log_print("[",(datetime.now().strftime("%Y-%m-%d %H:%M:%S")),"]: ")
                elif check_line_prefix(Current_line, "#END_NODE"):
                    # End of node block.
                    #log_print("[",(datetime.now().strftime("%Y-%m-%d %H:%M:%S")),"]: ","END_NODE[",node_info['node_number'],"]")
                                # Check for pause/stop commands
                    status = check_status_file(output_location) 
                    if status == 'pause':
                        log_print("[",(datetime.now().strftime("%Y-%m-%d %H:%M:%S")),"]: ","Script execution paused by user")
                        wait_while_paused(output_location)
                        log_print("[",(datetime.now().strftime("%Y-%m-%d %H:%M:%S")),"]: ","Script execution resumed")
                    elif status == 'stop':
                        break 
                        
                    if debug_mode:
                        show_debug_message(f'Degug mode::: Node[", {node_info['node_number']}] ,{node_info['node_type']}.........Press Enter to continue')
                elif check_line_prefix(Current_line, "Loop_end"):
                    #wait_while_paused(output_location)
                    # End of loop block; update iteration, possibly repeat, and log.
                    if write_flag==1 :
                        # Write timestamp and data line index to CSV, then advance line counter.
                        update_csv_cell(outpath,Data_line,"Date",datetime.now().strftime("%Y-%m-%d"))
                        update_csv_cell(outpath,Data_line,"Time",datetime.now().strftime("%H:%M:%S"))
                        update_csv_cell(outpath,Data_line,0,Data_line)
                        Data_line=Data_line+1
                        write_flag=0
                    # Update loop iteration counter and check if another iteration is needed.
                    this_loop_n=get_loop_end_number(Current_line)
                    loops[this_loop_n]['current_iteration']=(loops[this_loop_n]['current_iteration'])+1
                    log_print("[",(datetime.now().strftime("%Y-%m-%d %H:%M:%S")),"]: ","Ending loop (",this_loop_n,") At iteration= ",loops[this_loop_n]['current_iteration'])
                    if loops[this_loop_n]['current_iteration']<loops[this_loop_n]['iterations']:
                        # If loop not finished, set next step to loop start line.
                        Step_line=loops[this_loop_n]['line_index']
                        log_print("[",(datetime.now().strftime("%Y-%m-%d %H:%M:%S")),"]: ","Going back to loop at line ", Step_line)
                    else:
                        # Loop is done, reset current iteration count.
                        loops[this_loop_n]['current_iteration']=0
                        
                elif check_line_prefix(Current_line, "Delay:"):
                    # Explicit delay line: sleep for specified milliseconds.
                    delay_time=get_delay_in_ms(Current_line)/1000
                    log_print("[",(datetime.now().strftime("%Y-%m-%d %H:%M:%S")),"]: ","    Delay action for: ", delay_time," seconds")
                    time.sleep(delay_time)                    

                elif check_line_prefix(Current_line, "MESSAGE:"):
                    #print("I am here")
                    message_is =extract_prefixed_line(Current_line, "MESSAGE:")
                    write_status(f"{output_location}status.txt","pause")
                    # Check for pause/stop commands
                    status = check_status_file(output_location)
                    log_print("[",(datetime.now().strftime("%Y-%m-%d %H:%M:%S")),"]: ","Test paused with message: ", message_is)
                    script_line=script_line+1

                elif check_line_prefix(Current_line, "Work_flow:"):
                    
                    wf_name= extract_workflow_name(Current_line)
                    next_workflow= workflows_obi["workflows"][wf_name][0]
                    next_workflow_script= next_workflow.get(str("lines"))
                    next_workflow_path=(f"{output_location}{wf_name}.atoms")
                    create_subworkflow(next_workflow_script,next_workflow_path)
                    log_print("[",(datetime.now().strftime("%Y-%m-%d %H:%M:%S")),"]: ","Going to another workflow: ", wf_name, " at : ", next_workflow_path)
                    #print(json.dumps(next_workflow, indent=2))
                    separator=f"************************************************************ Starting script {wf_name} ************************************************************"
                    Data_line=Data_line+2
                    write_text_to_row_first_col(outpath,Data_line,separator)
                    temp_wf_csv= run_another_workflow(next_workflow_path,output_location,Data_line)
                    temp_log=f"{output_location}{temp_wf_csv}.log"
                    temp_wf_csv=f"{output_location}{temp_wf_csv}.csv"
                    Data_line= concat_csv_into_second(temp_wf_csv, outpath)-1
                    #separator=f"************************************************************ Ended script {wf_name} ************************************************************"
                    #write_text_to_row_first_col(outpath,Data_line+2,separator)
                    script_line=script_line+1
                    delete_csv_file(temp_wf_csv)
                    delete_csv_file(temp_log)
                    script_obj = parse_script_structured_v6(script_location)
                    current_node = script_obj["nodes"].get(str(node_id), {})   
                    next_node= current_node.get("next")

                
                #===================================================================================================================================================
                #===================================================================================================================================================
                #===================================================================================================================================================
                #===================================================================================================================================================    
                #================================================= Done Reading the line and executing it ==========================================================
                #===================================================================================================================================================
                #===================================================================================================================================================
                #===================================================================================================================================================
                script_line=script_line+1
                #script_obj = parse_script_structured_v6(script_location)
                #current_node = script_obj["nodes"].get(str(node_id), {})
                next_node= current_node.get("next")
                #print("Next node info is",current_node)
                if next_node.get("id")=="X":
                    running_script= False

                    
                text_line=read_line_from_script(script_location, script_line)    
                if check_line_prefix(text_line, "Loop_start"):
                    break
                    
                if check_line_prefix(text_line, "#NODE"):
                    break
            
            #=================================================== End While 2nd
                
            if not running_script:
                break    
            #else:
                #wait_while_paused(output_location)
                
                
            script_line= next_node.get("line")
            node_id = next_node.get("id")
            if next_node.get("type") == "LE":
                lid = str(next_node.get("id"))
                current_node = script_obj["loops"].setdefault(lid, {})
                current_node["current_iteration"] = int(current_node.get("current_iteration", 0)) + 1
                #log_print("======= LOOP", node_id, "======= Finished iteration ", current_node["current_iteration"]-1)
                Data_line=Data_line+1
            elif just_ended_loop:
                log_print("Loop ended and goint to:       ",current_node, )
                just_ended_loop= False
            else:
                current_node = script_obj["nodes"].get(str(next_node.get("id")), {})
            
            

            #log_print("========== Node ", next_node.get("type"),next_node.get("id"), "=================")    
            #print(current_node) 
            #print("=======================================")           
            next_node= current_node.get("next")

        #=================================================== End While 1st   
        

        
        if status=="stop":
            print_big_teststopped_banner()  
        else:
            if temp_csv:
                log_print("========== Sub script ended ==========")
            else:
                log_print("")
                print_big_testdone_banner()   
                
        # Save logs to file.
        log_file=f"{output_location}/{file_name}.log"
        save_all_logs(log_file)
        delete_status_file(output_location)
        
        if temp_csv:   
            return file_name
        else:
            return 0
            
        
        
        
        
     # *******************************************************************************************************************************
    # *******************************************************************************************************************************
    
    if not os.path.exists(script_path):
        print(f"\033[31mError: Script file does not exist: {script_path}\033[0m")
        # or: raise FileNotFoundError(f"Script file does not exist: {script_path}")
        return

    if not os.path.exists(output_path):
        try:
            os.makedirs(output_path, exist_ok=True)
        except Exception as e:
            print(f"\033[31mError: Cannot create output directory: {e}\033[0m")
            # or: raise
            return

    # ---- Main execution logic (your original code) ----
    set_total_steps(compute_loop_weight(script_path))

    out_file = run_script_new(script_path, output_path,False,debug_mode)

    final_step = 100
    final_total_steps = compute_loop_weight(script_path)
        

