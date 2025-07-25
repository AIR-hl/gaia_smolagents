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
import os
import re
import shutil
import queue
import threading
from pathlib import Path
from typing import Generator
import html

from smolagents.agent_types import AgentAudio, AgentImage, AgentText
from smolagents.agents import MultiStepAgent, PlanningStep
from smolagents.memory import ActionStep, FinalAnswerStep
from smolagents.models import ChatMessageStreamDelta, MessageRole, agglomerate_stream_deltas
from smolagents.utils import _is_package_available
from smolagents.monitoring import AgentLogger, LogLevel


def get_step_footnote_content(step_log: ActionStep | PlanningStep, step_name: str) -> str:
    """Get a footnote string for a step log with duration and token information"""
    step_footnote = f"**{step_name}**"
    if step_log.token_usage is not None:
        step_footnote += f" | Input tokens: {step_log.token_usage.input_tokens:,} | Output tokens: {step_log.token_usage.output_tokens:,}"
    step_footnote += f" | Duration: {round(float(step_log.timing.duration), 2)}s" if step_log.timing.duration else ""
    return step_footnote


def _clean_model_output(model_output: str | None) -> str:
    """
    Clean up model output by removing trailing tags and extra backticks.

    Args:
        model_output (`str`): Raw model output.

    Returns:
        `str`: Cleaned model output.
    """
    if not model_output:
        return ""
    model_output = model_output.strip()
    # Remove any trailing <end_code> and extra backticks, handling multiple possible formats
    model_output = re.sub(r"```\s*<end_code>", "```", model_output)  # handles ```<end_code>
    model_output = re.sub(r"<end_code>\s*```", "```", model_output)  # handles <end_code>```
    model_output = re.sub(r"```\s*\n\s*<end_code>", "```", model_output)  # handles ```\n<end_code>
    return model_output.strip()


def _format_code_content(content: str) -> str:
    """
    Format code content as Python code block if it's not already formatted.

    Args:
        content (`str`): Code content to format.

    Returns:
        `str`: Code content formatted as a Python code block.
    """
    content = content.strip()
    # Remove existing code blocks and end_code tags
    content = re.sub(r"```.*?\n", "", content)
    content = re.sub(r"\s*<end_code>\s*", "", content)
    content = content.strip()
    # Add Python code block formatting if not already present
    if not content.startswith("```python"):
        content = f"```python\n{content}\n```"
    return content


def _process_action_step(step_log: ActionStep, skip_model_outputs: bool = False) -> Generator:
    """
    Process an [`ActionStep`] and yield appropriate Gradio ChatMessage objects.

    Args:
        step_log ([`ActionStep`]): ActionStep to process.
        skip_model_outputs (`bool`): Whether to skip model outputs.

    Yields:
        `gradio.ChatMessage`: Gradio ChatMessages representing the action step.
    """
    import gradio as gr

    # Output the step number
    step_number = f"Step {step_log.step_number}"
    if not skip_model_outputs:
        yield gr.ChatMessage(
            role=MessageRole.ASSISTANT.value, content=f"**{step_number}**", metadata={"status": "done"}
        )

    # First yield the thought/reasoning from the LLM
    if not skip_model_outputs and getattr(step_log, "model_output", ""):
        model_output_content = step_log.model_output
        if model_output_content:
            if isinstance(model_output_content, list):
                model_output_content = str(model_output_content)
            model_output = _clean_model_output(model_output_content)
            yield gr.ChatMessage(role=MessageRole.ASSISTANT.value, content=model_output, metadata={"status": "done"})

    # For tool calls, create a parent message
    if step_log.tool_calls:
        first_tool_call = step_log.tool_calls[0]
        used_code = first_tool_call.name == "python_interpreter"

        # Process arguments based on type
        args = first_tool_call.arguments
        content = ""
        if args:
            if isinstance(args, dict):
                content = str(args.get("answer", str(args)))
            else:
                content = str(args).strip()

        # Format code content if needed
        if used_code:
            content = _format_code_content(content)

        # Create the tool call message
        parent_message_tool = gr.ChatMessage(
            role=MessageRole.ASSISTANT.value,
            content=content,
            metadata={
                "title": f"🛠️ Used tool {first_tool_call.name}",
                "status": "done",
            },
        )
        yield parent_message_tool

    # Display execution logs if they exist
    if step_log.observations and step_log.observations.strip():
        log_content = step_log.observations.strip()
        if log_content:
            log_content = re.sub(r"^Execution logs:\s*", "", log_content)
            yield gr.ChatMessage(
                role=MessageRole.ASSISTANT.value,
                content=f"```bash\n{log_content}\n",
                metadata={"title": "📝 Execution Logs", "status": "done"},
            )

    # Display any images in observations
    if step_log.observations_images:
        for image in step_log.observations_images:
            path_image_str = str(AgentImage(image).to_string())
            _, extension = os.path.splitext(path_image_str)
            yield gr.ChatMessage(
                role=MessageRole.ASSISTANT.value,
                content=(path_image_str,),
                metadata={"title": "🖼️ Output Image", "status": "done"},
            )

    # Handle errors
    if getattr(step_log, "error", None):
        yield gr.ChatMessage(
            role=MessageRole.ASSISTANT.value,
            content=str(step_log.error),
            metadata={"title": "💥 Error", "status": "done"},
        )

    # Add step footnote and separator
    yield gr.ChatMessage(
        role=MessageRole.ASSISTANT.value,
        content=get_step_footnote_content(step_log, step_number),
        metadata={"status": "done"},
    )
    yield gr.ChatMessage(role=MessageRole.ASSISTANT.value, content="-----", metadata={"status": "done"})


def _process_planning_step(step_log: PlanningStep, skip_model_outputs: bool = False) -> Generator:
    """
    Process a [`PlanningStep`] and yield appropriate gradio.ChatMessage objects.

    Args:
        step_log ([`PlanningStep`]): PlanningStep to process.

    Yields:
        `gradio.ChatMessage`: Gradio ChatMessages representing the planning step.
    """
    import gradio as gr

    if not skip_model_outputs:
        yield gr.ChatMessage(role=MessageRole.ASSISTANT.value, content="**Planning step**", metadata={"status": "done"})
        yield gr.ChatMessage(role=MessageRole.ASSISTANT.value, content=step_log.plan, metadata={"status": "done"})
    yield gr.ChatMessage(
        role=MessageRole.ASSISTANT.value,
        content=get_step_footnote_content(step_log, "Planning step"),
        metadata={"status": "done"},
    )
    yield gr.ChatMessage(role=MessageRole.ASSISTANT.value, content="-----", metadata={"status": "done"})


def _process_final_answer_step(step_log: FinalAnswerStep) -> Generator:
    """
    Process a [`FinalAnswerStep`] and yield appropriate gradio.ChatMessage objects.

    Args:
        step_log ([`FinalAnswerStep`]): FinalAnswerStep to process.

    Yields:
        `gradio.ChatMessage`: Gradio ChatMessages representing the final answer.
    """
    import gradio as gr

    final_answer = step_log.output
    if isinstance(final_answer, AgentText):
        yield gr.ChatMessage(
            role=MessageRole.ASSISTANT.value,
            content=f"**Final answer:**\n{final_answer.to_string()}\n",
            metadata={"status": "done"},
        )
    elif isinstance(final_answer, AgentImage):
        yield gr.ChatMessage(
            role=MessageRole.ASSISTANT.value,
            content={"path": final_answer.to_string(), "mime_type": "image/png"},
            metadata={"status": "done"},
        )
    elif isinstance(final_answer, AgentAudio):
        yield gr.ChatMessage(
            role=MessageRole.ASSISTANT.value,
            content={"path": final_answer.to_string(), "mime_type": "audio/wav"},
            metadata={"status": "done"},
        )
    else:
        yield gr.ChatMessage(
            role=MessageRole.ASSISTANT.value,
            content=f"**Final answer:** {str(final_answer)}",
            metadata={"status": "done"},
        )


def pull_messages_from_step(step_log: ActionStep | PlanningStep | FinalAnswerStep, skip_model_outputs: bool = False):
    """Extract Gradio ChatMessage objects from agent steps with proper nesting.

    Args:
        step_log: The step log to display as gr.ChatMessage objects.
        skip_model_outputs: If True, skip the model outputs when creating the gr.ChatMessage objects:
            This is used for instance when streaming model outputs have already been displayed.
    """
    if not _is_package_available("gradio"):
        raise ModuleNotFoundError(
            "Please install 'gradio' extra to use the GradioUI: `pip install 'smolagents[gradio]'`"
        )
    if isinstance(step_log, ActionStep):
        yield from _process_action_step(step_log, skip_model_outputs)
    elif isinstance(step_log, PlanningStep):
        yield from _process_planning_step(step_log, skip_model_outputs)
    elif isinstance(step_log, FinalAnswerStep):
        yield from _process_final_answer_step(step_log)
    else:
        raise ValueError(f"Unsupported step type: {type(step_log)}")


def stream_to_gradio(
    agent,
    task: str,
    task_images: list | None = None,
    additional_args: dict | None = None,
) -> Generator:
    """
    Stream the agent's response to Gradio.

    Args:
        agent: The agent to run.
        task (str): The task to perform.
        task_images (list, optional): A list of images for the task. Defaults to None.
        additional_args (dict, optional): Additional arguments for the agent. Defaults to None.

    Yields:
        Generator: A generator of Gradio ChatMessage objects.
    """
    if not _is_package_available("gradio"):
        raise ModuleNotFoundError(
            "Please install 'gradio' extra to use the GradioUI: `pip install 'smolagents[gradio]'`"
        )
    import gradio as gr

    # First, yield the user's message
    yield gr.ChatMessage(
        role=MessageRole.USER.value,
        content=task,
        avatar_image=os.path.join(os.path.dirname(__file__), "assets/user.png"),
        metadata={"status": "done"},
    )

    # Then, stream the agent's response
    stream = agent.run(task, stream=True, reset=False, images=task_images, additional_args=additional_args)

    model_output = ""
    skip_model_outputs = False
    for step_log in stream:
        if isinstance(step_log, ChatMessageStreamDelta):
            # Stream the model output as it comes
            model_output = agglomerate_stream_deltas([step_log]).content
            if model_output is not None:
                yield gr.ChatMessage(
                    role=MessageRole.ASSISTANT.value, content=model_output, metadata={"status": "pending"}
                )
            skip_model_outputs = True
        elif isinstance(step_log, (ActionStep, PlanningStep, FinalAnswerStep)):
            # Once the model output is finished, replace the last message with the full one
            if skip_model_outputs:
                yield gr.ChatMessage(
                    role=MessageRole.ASSISTANT.value, content=model_output, metadata={"status": "done"}
                )

            # And proceed with displaying the other step logs
            yield from pull_messages_from_step(step_log, skip_model_outputs=skip_model_outputs)
            skip_model_outputs = False


class GradioUI:
    """
    A Gradio UI for interacting with a multi-step agent.

    Args:
        agent (MultiStepAgent): The agent to interact with.
        file_upload_folder (str, optional): The folder to upload files to. Defaults to None.
        reset_agent_memory (bool, optional): Whether to reset the agent's memory for each interaction. Defaults to False.
    """

    def __init__(self, agent: MultiStepAgent, file_upload_folder: str | None = None, reset_agent_memory: bool = False):
        if not _is_package_available("gradio"):
            raise ModuleNotFoundError(
                "Please install 'gradio' extra to use the GradioUI: `pip install 'smolagents[gradio]'`"
            )
        self.agent = agent
        self.file_upload_folder = file_upload_folder or "uploads"
        self.reset_agent_memory = reset_agent_memory
        self.log_queue = queue.Queue()
        self.log_html_content = ""
        self.log_files = self._find_log_files()

    def _find_log_files(self):
        log_dir = Path("log")
        if not log_dir.exists():
            return []
        return sorted([str(f) for f in log_dir.rglob("*.log")], reverse=True)

    def display_log_content(self, log_file_path):
        """
        Read and display the content of a selected log file.
        """
        if not log_file_path:
            return """
            <div style="text-align: center; padding: 20px; color: #666;">
                <h3>📂 Historical Log Viewer</h3>
                <p>Select a log file from the dropdown above to view its content.</p>
                <p><small>Log files are automatically saved when the agent runs.</small></p>
            </div>
            """
        try:
            with open(log_file_path, "r", encoding="utf-8") as f:
                content = f.read()
            # Escape HTML and wrap in <pre> for monospaced font and preserved formatting
            escaped_content = html.escape(content)
            # Add JavaScript to scroll to bottom and maintain scroll position
            html_content = f"""
            <div style="margin-bottom: 10px;"><strong>📄 Log File:</strong> {log_file_path}</div>
            <div id="log-container" style="max-height: 600px; overflow-y: auto; border: 1px solid #ccc; padding: 10px; background-color: #f8f9fa;">
                <pre id="log-content" style="margin: 0; white-space: pre-wrap; word-wrap: break-word;">{escaped_content}</pre>
            </div>
            <script>
                (function() {{
                    const container = document.getElementById('log-container');
                    if (!container) return;

                    // Restore scroll position after Gradio update
                    if (typeof window.isSmolAtBottom !== 'undefined' && window.isSmolAtBottom) {{
                        container.scrollTop = container.scrollHeight;
                    }} else if (typeof window.smolScrollTop !== 'undefined') {{
                        container.scrollTop = window.smolScrollTop;
                    }}

                    // Add listener to save scroll position for the *next* update
                    container.onscroll = () => {{
                        window.smolScrollTop = container.scrollTop;
                        window.isSmolAtBottom = container.scrollTop + container.clientHeight >= container.scrollHeight - 5;
                    }};

                    // Initial setup on first load
                    if (typeof window.isSmolAtBottom === 'undefined') {{
                        window.isSmolAtBottom = true;
                        setTimeout(() => {{ container.scrollTop = container.scrollHeight; }}, 100);
                    }}
                }})();
            </script>
            """
            return html_content
        except Exception as e:
            return f"<h3>❌ Error reading log file: {e}</h3>"

    def interact_with_agent(self, prompt, messages, session_state):
        """
        The main interaction loop for the agent.
        It streams the agent's response to the Gradio UI.
        """
        import gradio as gr

        if self.reset_agent_memory:
            self.agent.memory.reset()

        # Set up a new logger with a handler that puts logs into the queue
        log_handler = self.log_queue.put
        self.agent.logger = AgentLogger(level=LogLevel.INFO, log_handler=log_handler)

        task_images = session_state.get("task_images", [])

        # Activate the timer
        yield gr.Timer(1, active=True), messages

        # Run the agent and stream the results
        for new_messages in self.run_agent_and_stream(prompt, task_images, messages):
            yield gr.Timer(1, active=True), new_messages

        # Deactivate the timer
        yield gr.Timer(1, active=False), messages

    def run_agent_and_stream(self, prompt, task_images, messages):
        """
        A helper to run the agent in a thread and update messages.
        This is not directly called by Gradio events.
        """
        # We don't use the generator directly here, but it's consumed by Gradio's streaming mechanism
        # The actual updates to `messages` happen through the `yield`s in `stream_to_gradio`
        # which Gradio handles.
        for message_chunk in stream_to_gradio(
            self.agent,
            prompt,
            task_images=task_images,
        ):
            messages.append(message_chunk)
            yield messages

    def upload_file(self, file, file_uploads_log, allowed_file_types=None):
        """
        Handle file uploads from the user.
        """
        import gradio as gr

        if not os.path.exists(self.file_upload_folder):
            os.makedirs(self.file_upload_folder)

        file_path = file.name
        file_name = Path(file_path).name
        destination_path = os.path.join(self.file_upload_folder, file_name)

        shutil.copy(file_path, destination_path)
        file_type = file_name.split(".")[-1].lower()

        if allowed_file_types and file_type not in allowed_file_types:
            return (
                file_uploads_log
                + [
                    (
                        None,
                        f"File type '{file_type}' not allowed. Allowed types are: {', '.join(allowed_file_types)}",
                    )
                ],
                gr.update(value=None),
            )

        if file_type in ["jpg", "jpeg", "png", "gif", "bmp"]:
            return file_uploads_log + [(destination_path, file_name)], gr.update(value=None)
        elif file_type in ["wav", "mp3", "flac"]:
            return file_uploads_log + [(destination_path, file_name)], gr.update(value=None)
        else:
            return file_uploads_log + [(destination_path, f"File: {file_name}")], gr.update(value=None)

    def log_user_message(self, text_input, file_uploads_log, messages):
        """
        Log the user's message and file uploads to the chatbot.
        """
        import gradio as gr

        if text_input:
            messages.append(
                gr.ChatMessage(
                    role="user",
                    content=text_input,
                    avatar_image=os.path.join(os.path.dirname(__file__), "assets/user.png"),
                )
            )
        if file_uploads_log:
            for file_path, file_name in file_uploads_log:
                messages.append(
                    gr.ChatMessage(
                        role="user",
                        content=(file_path, file_name),
                        avatar_image=os.path.join(os.path.dirname(__file__), "assets/user.png"),
                    )
                )
        return "", [], messages

    def launch(self, share: bool = True, **kwargs):
        """

        Launch the Gradio UI.
        """
        self.create_app().launch(share=share, **kwargs)

    def update_logs(self):
        """
        Update the logs in the UI by reading from the queue.
        """
        while not self.log_queue.empty():
            log_record = self.log_queue.get_nowait()
            self.log_html_content += html.escape(str(log_record)) + "<br>"
        
        if self.log_html_content:
            # Wrap in a scrollable container with auto-scroll to bottom
            formatted_content = f"""
            <div id="realtime-log-container" style="max-height: 600px; overflow-y: auto; border: 1px solid #ccc; padding: 10px; background-color: #f8f9fa;">
                <div id="realtime-log-content" style="font-family: monospace; white-space: pre-wrap; word-wrap: break-word;">{self.log_html_content}</div>
            </div>
            <script>
                (function() {{
                    const container = document.getElementById('realtime-log-container');
                    if (!container) return;

                    // Restore scroll position after Gradio update
                    if (typeof window.isSmolRealtimeAtBottom !== 'undefined' && window.isSmolRealtimeAtBottom) {{
                        container.scrollTop = container.scrollHeight;
                    }} else if (typeof window.smolRealtimeScrollTop !== 'undefined') {{
                        container.scrollTop = window.smolRealtimeScrollTop;
                    }}

                    // Add listener to save scroll position for the *next* update
                    container.onscroll = () => {{
                        window.smolRealtimeScrollTop = container.scrollTop;
                        window.isSmolRealtimeAtBottom = container.scrollTop + container.clientHeight >= container.scrollHeight - 5;
                    }};

                    // Initial setup on first load
                    if (typeof window.isSmolRealtimeAtBottom === 'undefined') {{
                        window.isSmolRealtimeAtBottom = true;
                        setTimeout(() => {{ container.scrollTop = container.scrollHeight; }}, 100);
                    }}
                }})();
            </script>
            """
            return formatted_content
        else:
            return """
            <div style="text-align: center; padding: 20px; color: #666;">
                <h3>📊 Real-time Agent Logs</h3>
                <p>🔄 Logs will appear here when the agent is running...</p>
                <p><small>The view will automatically scroll to show the latest logs.</small></p>
            </div>
            """

    def create_app(self):
        """
        Create the Gradio app.
        """
        import gradio as gr

        with gr.Blocks() as demo:
            session_state = gr.State({})
            with gr.Row():
                with gr.Column(scale=1):
                    chatbot = gr.Chatbot(
                        [],
                        elem_id="chatbot",
                        bubble_full_width=False,
                        avatar_images=(
                            os.path.join(os.path.dirname(__file__), "assets/user.png"),
                            os.path.join(os.path.dirname(__file__), "assets/logo.png"),
                        ),
                    )
                with gr.Column(scale=1):
                    log_viewer = gr.HTML("""
                    <div style="text-align: center; padding: 20px; color: #666;">
                        <h3>📊 Real-time Agent Logs</h3>
                        <p>🔄 Logs will appear here when the agent is running...</p>
                        <p><small>The view will automatically scroll to show the latest logs.</small></p>
                    </div>
                    """)
                    with gr.Row():
                        log_file_dropdown = gr.Dropdown(
                            label="📂 Select a past log file to view", choices=self.log_files, scale=10, 
                            info="Choose from previously saved log files"
                        )
                        load_log_button = gr.Button("📄 Load", scale=1, size="sm")
                    timer = gr.Timer(1, active=False)

            with gr.Row():
                text_input = gr.Textbox(
                    scale=4,
                    show_label=False,
                    placeholder="Enter text and press enter, or upload an image",
                    container=False,
                )
                upload_button = gr.UploadButton("📁", file_types=["image", "video", "audio"])

            file_uploads_log = gr.State([])

            text_input.submit(
                self.log_user_message,
                [text_input, file_uploads_log, chatbot],
                [text_input, file_uploads_log, chatbot],
                queue=False,
            ).then(
                self.interact_with_agent,
                [text_input, chatbot, session_state],
                [timer, chatbot],
            )

            upload_button.upload(
                self.upload_file,
                [upload_button, file_uploads_log],
                [file_uploads_log, upload_button],
                queue=False,
            ).then(
                lambda s: s.update(interactive=True),
                None,
                [text_input],
                queue=False,
            )

            load_log_button.click(
                self.display_log_content,
                inputs=[log_file_dropdown],
                outputs=[log_viewer],
            )

            timer.tick(self.update_logs, None, log_viewer)

        return demo


__all__ = ["stream_to_gradio", "GradioUI"]
