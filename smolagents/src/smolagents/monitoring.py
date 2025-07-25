#!/usr/bin/env python
# coding=utf-8

# Copyright 2024 The HuggingFace Inc. team. All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
import json
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any, Callable
import time
from datetime import datetime

from rich import box
from rich.console import Console, Group
from rich.panel import Panel
from rich.rule import Rule
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text
from rich.tree import Tree
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.align import Align

from smolagents.utils import escape_code_brackets


__all__ = ["AgentLogger", "LogLevel", "Monitor", "TokenUsage", "Timing"]


@dataclass
class TokenUsage:
    """
    Contains the token usage information for a given step or run.
    """

    input_tokens: int
    output_tokens: int
    total_tokens: int = field(init=False)

    def __post_init__(self):
        self.total_tokens = self.input_tokens + self.output_tokens

    def dict(self):
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
        }


@dataclass
class Timing:
    """
    Contains the timing information for a given step or run.
    """

    start_time: float
    end_time: float | None = None

    @property
    def duration(self):
        return None if self.end_time is None else self.end_time - self.start_time

    def dict(self):
        return {
            "start_time": self.start_time,
            "end_time": self.end_time,
            "duration": self.duration,
        }

    def __repr__(self) -> str:
        return f"Timing(start_time={self.start_time}, end_time={self.end_time}, duration={self.duration})"


class Monitor:
    def __init__(self, tracked_model, logger):
        self.step_durations = []
        self.tracked_model = tracked_model
        self.logger = logger
        self.total_input_token_count = 0
        self.total_output_token_count = 0

    def get_total_token_counts(self) -> TokenUsage:
        return TokenUsage(
            input_tokens=self.total_input_token_count,
            output_tokens=self.total_output_token_count,
        )

    def reset(self):
        self.step_durations = []
        self.total_input_token_count = 0
        self.total_output_token_count = 0

    def update_metrics(self, step_log):
        """Update the metrics of the monitor.

        Args:
            step_log ([`MemoryStep`]): Step log to update the monitor with.
        """
        step_duration = step_log.timing.duration
        self.step_durations.append(step_duration)
        console_outputs = f"Step {len(self.step_durations)}: Duration {step_duration:.2f} seconds"

        if step_log.token_usage is not None:
            self.total_input_token_count += step_log.token_usage.input_tokens
            self.total_output_token_count += step_log.token_usage.output_tokens
            console_outputs += (
                f"| Input tokens: {self.total_input_token_count:,} | Output tokens: {self.total_output_token_count:,}"
            )
        self.logger.log(console_outputs, level=1)


class LogLevel(IntEnum):
    OFF = -1  # No output
    ERROR = 0  # Only errors
    INFO = 1  # Normal output (default)
    DEBUG = 2  # Detailed output


YELLOW_HEX = "#d4b702"
BLUE_HEX = "#0066cc"
GREEN_HEX = "#28a745"
RED_HEX = "#dc3545"
PURPLE_HEX = "#6f42c1"


class AgentLogger:
    def __init__(
        self,
        level: LogLevel = LogLevel.INFO,
        console: Console | None = None,
        log_handler: Callable[[Any], None] | None = None,
    ):
        self.level = level
        if console is None:
            self.console = Console()
        else:
            self.console = console
        self.log_handler = log_handler

    def log(self, *args, level: int | str | LogLevel = LogLevel.INFO, **kwargs) -> None:
        """Logs a message to the console.

        Args:
            level (LogLevel, optional): Defaults to LogLevel.INFO.
        """
        if isinstance(level, str):
            level = LogLevel[level.upper()]
        if level <= self.level:
            self.console.print(*args, **kwargs)

            if self.log_handler:
                # To capture just this message, create a temporary console, print to it, and export.
                temp_console = Console(record=True, width=self.console.width)
                temp_console.print(*args, **kwargs)
                # Exporting with inline styles will make it self-contained
                html_output = temp_console.export_html(inline_styles=True, code_format="<pre>{code}</pre>")
                self.log_handler(html_output)

    def log_error(self, error_message: str) -> None:
        """Enhanced error logging with better formatting"""
        # Create an error panel with timestamp
        timestamp = datetime.now().strftime("%H:%M:%S")
        error_panel = Panel(
            f"[bold red]ERROR[/bold red] [{timestamp}]\n\n{escape_code_brackets(error_message)}",
            title="🚨 Error",
            border_style="red",
            padding=(1, 2)
        )
        self.log(error_panel, level=LogLevel.ERROR)

    def log_markdown(self, content: str, title: str | None = None, level=LogLevel.INFO, style=YELLOW_HEX) -> None:
        """Enhanced markdown logging with better formatting"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        
        if title:
            # Create a styled panel for markdown content
            panel = Panel(
                content,
                title=f"📝 {title}",
                subtitle=f"[dim]{timestamp}[/dim]",
                border_style="yellow",
                padding=(1, 2)
            )
            self.log(panel, level=level)
        else:
            self.log(content, level=level)

    def log_code(self, title: str, content: str, level: int = LogLevel.INFO, language: str = "python") -> None:
        """Enhanced code logging with syntax highlighting"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        
        # Create syntax highlighted code
        syntax = Syntax(content, language, theme="monokai", line_numbers=True, background_color="default")
        
        # Wrap in a panel
        panel = Panel(
            syntax,
            title=f"💻 {title}",
            subtitle=f"[dim]{timestamp}[/dim]",
            border_style="blue",
            padding=(1, 2)
        )
        self.log(panel, level=level)

    def log_rule(self, title: str, level: int = LogLevel.INFO, style: str = "bold blue") -> None:
        """Enhanced rule logging with better visual separation"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        
        # Create a more visually appealing rule
        rule = Rule(
            title=f"[{style}]{title}[/{style}] [{timestamp}]",
            style="blue",
            characters="─"
        )
        self.log(rule, level=level)

    def log_task_start(self, task_id: str, task_description: str = "", level: int = LogLevel.INFO) -> None:
        """Log task start with enhanced formatting"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        # Create a task info table
        table = Table(show_header=False, show_edge=False, padding=(0, 1))
        table.add_column("Label", style="bold cyan", width=12)
        table.add_column("Value", style="white")
        
        table.add_row("🆔 Task ID:", f"[bold]{task_id}[/bold]")
        table.add_row("⏰ Started:", timestamp)
        if task_description:
            table.add_row("📋 Task:", task_description)
        
        panel = Panel(
            table,
            title="🎯 Task Started",
            border_style="green",
            padding=(1, 2)
        )
        self.log(panel, level=level)

    def log_task_end(self, task_id: str, duration: float | None = None, status: str = "completed", level: int = LogLevel.INFO) -> None:
        """Log task end with enhanced formatting"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        # Choose emoji and color based on status
        status_emoji = "✅" if status == "completed" else "❌" if status == "failed" else "⏸️"
        status_color = "green" if status == "completed" else "red" if status == "failed" else "yellow"
        
        # Create a task summary table
        table = Table(show_header=False, show_edge=False, padding=(0, 1))
        table.add_column("Label", style="bold cyan", width=12)
        table.add_column("Value", style="white")
        
        table.add_row(f"{status_emoji} Task ID:", f"[bold]{task_id}[/bold]")
        table.add_row("⏰ Finished:", timestamp)
        table.add_row("📊 Status:", f"[{status_color}]{status.upper()}[/{status_color}]")
        if duration:
            table.add_row("⏱️ Duration:", f"{duration:.2f}s")
        
        panel = Panel(
            table,
            title=f"{status_emoji} Task {status.title()}",
            border_style=status_color,
            padding=(1, 2)
        )
        self.log(panel, level=level)

    def log_step(self, step_number: int, step_type: str = "", level: int = LogLevel.INFO) -> None:
        """Log step with enhanced formatting"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        
        step_text = f"Step {step_number}"
        if step_type:
            step_text += f" - {step_type}"
        
        rule = Rule(
            title=f"[bold yellow]🔄 {step_text}[/bold yellow] [dim]({timestamp})[/dim]",
            style="yellow",
            characters="═"
        )
        self.log(rule, level=level)

    def log_metrics(self, metrics: dict, title: str = "Metrics", level: int = LogLevel.INFO) -> None:
        """Log metrics in a formatted table"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        
        table = Table(title=f"📊 {title}", show_header=True, header_style="bold magenta")
        table.add_column("Metric", style="cyan", width=20)
        table.add_column("Value", style="white", justify="right")
        
        for key, value in metrics.items():
            if isinstance(value, (int, float)):
                if isinstance(value, float):
                    formatted_value = f"{value:.2f}"
                else:
                    formatted_value = f"{value:,}"
            else:
                formatted_value = str(value)
            table.add_row(key, formatted_value)
        
        panel = Panel(
            table,
            subtitle=f"[dim]{timestamp}[/dim]",
            border_style="magenta",
            padding=(1, 2)
        )
        self.log(panel, level=level)

    def log_task(self, content: str, subtitle: str, title: str | None = None, level: LogLevel = LogLevel.INFO) -> None:
        """Enhanced task logging"""
        log_title = "New run" + (f" - {title}" if title else "")
        timestamp = datetime.now().strftime("%H:%M:%S")
        
        # Create a structured task display
        task_content = f"[bold cyan]{subtitle}[/bold cyan]\n\n{content}"
        
        panel = Panel(
            task_content,
            title=f"🤖 {log_title}",
            subtitle=f"[dim]{timestamp}[/dim]",
            border_style="green",
            padding=(1, 2)
        )
        self.log(panel, level=level)

    def log_messages(self, messages: list[dict], level: LogLevel = LogLevel.DEBUG) -> None:
        """Enhanced message logging with better formatting"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        
        # Format messages in a more readable way
        formatted_messages = []
        for i, message in enumerate(messages, 1):
            role = message.get('role', 'unknown')
            content = message.get('content', '')
            
            # Truncate long content for readability
            if len(content) > 200:
                content = content[:200] + "..."
            
            formatted_messages.append(f"[bold]{i}. {role.upper()}:[/bold]\n{content}")
        
        messages_content = "\n\n".join(formatted_messages)
        
        panel = Panel(
            messages_content,
            title="💬 Messages",
            subtitle=f"[dim]{timestamp} - {len(messages)} messages[/dim]",
            border_style="blue",
            padding=(1, 2)
        )
        self.log(panel, level=level)

    def visualize_agent_tree(self, agent):
        """Enhanced agent tree visualization"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        
        def get_agent_headline(agent, name: str | None = None):
            name_headline = f"{name} | " if name else ""
            return f"{name_headline}{agent.__class__.__name__} | {agent.model.model_id}"

        def build_agent_tree(agent_obj, tree_node=None, prefix=""):
            if tree_node is None:
                # Root node
                tree = Tree(f"🤖 {get_agent_headline(agent_obj, getattr(agent_obj, 'name', None))}")
                tree_node = tree
            else:
                # Add as child
                tree_node = tree_node.add(f"🤖 {get_agent_headline(agent_obj, getattr(agent_obj, 'name', None))}")
            
            if hasattr(agent_obj, 'tools') and agent_obj.tools:
                tools_node = tree_node.add("🛠️  Tools")
                for name, tool in agent_obj.tools.items():
                    tools_node.add(f"⚙️  {name}: {getattr(tool, 'description', 'No description')[:50]}...")

            if hasattr(agent_obj, 'managed_agents') and agent_obj.managed_agents:
                agents_node = tree_node.add("👥 Managed Agents")
                for name, managed_agent in agent_obj.managed_agents.items():
                    build_agent_tree(managed_agent, agents_node)
            
            return tree_node if tree_node != tree else tree

        tree = build_agent_tree(agent)
        
        panel = Panel(
            tree,
            title="🌳 Agent Structure",
            subtitle=f"[dim]{timestamp}[/dim]",
            border_style="green",
            padding=(1, 2)
        )
        self.log(panel)
