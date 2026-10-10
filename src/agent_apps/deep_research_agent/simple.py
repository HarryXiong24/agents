import gradio as gr

from .research_manager import ResearchManager


async def run(query: str):
    async for status_update in ResearchManager().run(query):
        yield status_update


with gr.Blocks() as ui:
    query_textbox = gr.Textbox(label="What topic would you like to research?")
    run_button = gr.Button("Run", variant="primary")
    report = gr.Markdown(label="Report")

    run_button.click(run, inputs=query_textbox, outputs=report)
    query_textbox.submit(run, inputs=query_textbox, outputs=report)

ui.launch(theme=gr.themes.Default(primary_hue="sky"))
