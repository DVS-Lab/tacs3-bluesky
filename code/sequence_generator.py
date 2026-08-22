import html
import shutil
import threading
import webbrowser

from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs


# Put test.csv in the same folder as this Python script.
SOURCE_FILE = Path(__file__).resolve().parent / "test.csv"


class FormHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_html(
            """
            <!DOCTYPE html>
            <html lang="en">
            <head>
                <meta charset="UTF-8">
                <title>Create Subject File</title>

                <style>
                    body {
                        font-family: Arial, sans-serif;
                        background: #f4f4f4;
                        margin: 0;
                        display: flex;
                        justify-content: center;
                        align-items: center;
                        height: 100vh;
                    }

                    .box {
                        background: white;
                        padding: 30px;
                        border-radius: 10px;
                        box-shadow: 0 4px 15px rgba(0, 0, 0, 0.15);
                        width: 350px;
                    }

                    label {
                        display: block;
                        margin-bottom: 8px;
                        font-weight: bold;
                    }

                    input {
                        box-sizing: border-box;
                        width: 100%;
                        padding: 12px;
                        font-size: 18px;
                        color: black;
                        background: white;
                        border: 1px solid #777;
                        border-radius: 5px;
                        margin-bottom: 15px;
                    }

                    button {
                        width: 100%;
                        padding: 12px;
                        font-size: 16px;
                        cursor: pointer;
                    }
                </style>
            </head>

            <body>
                <div class="box">
                    <form method="POST">
                        <label for="subject_id">Subject ID</label>

                        <input
                            id="subject_id"
                            name="subject_id"
                            type="text"
                            autocomplete="off"
                            autofocus
                            required
                        >

                        <button type="submit">Create File</button>
                    </form>
                </div>
            </body>
            </html>
            """
        )

    def do_POST(self):
        content_length = int(self.headers.get("Content-Length", 0))
        form_data = self.rfile.read(content_length).decode("utf-8")
        values = parse_qs(form_data)

        subject_id = values.get("subject_id", [""])[0].strip()

        invalid_characters = '<>:"/\\|?*'

        if not subject_id:
            self.show_result("Error", "Please enter a subject ID.")
            return

        if any(character in subject_id for character in invalid_characters):
            self.show_result(
                "Invalid Subject ID",
                "The subject ID contains a character that cannot be used "
                "in a filename."
            )
            return

        if not SOURCE_FILE.exists():
            self.show_result(
                "Source File Missing",
                f"Could not find {SOURCE_FILE.name} in the script folder."
            )
            return

        destination = SOURCE_FILE.with_name(f"{subject_id}.csv")

        try:
            shutil.copy2(SOURCE_FILE, destination)
        except OSError as error:
            self.show_result("File Error", str(error))
            return

        self.show_result(
            "File Created",
            f"Created: {destination}"
        )

        # Shut down the temporary server after submission.
        threading.Thread(
            target=self.server.shutdown,
            daemon=True
        ).start()

    def show_result(self, title, message):
        safe_title = html.escape(title)
        safe_message = html.escape(message)

        self.send_html(
            f"""
            <!DOCTYPE html>
            <html lang="en">
            <head>
                <meta charset="UTF-8">
                <title>{safe_title}</title>
            </head>

            <body style="
                font-family: Arial, sans-serif;
                padding: 40px;
                text-align: center;
            ">
                <h2>{safe_title}</h2>
                <p>{safe_message}</p>
                <p>You may close this browser tab.</p>
            </body>
            </html>
            """
        )

    def send_html(self, content):
        encoded_content = content.encode("utf-8")

        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded_content)))
        self.end_headers()

        self.wfile.write(encoded_content)

    def log_message(self, format, *args):
        # Prevent routine server messages from cluttering the terminal.
        return


def main():
    # Port 0 asks the operating system to select an available port.
    server = HTTPServer(("127.0.0.1", 0), FormHandler)
    port = server.server_address[1]

    address = f"http://127.0.0.1:{port}"

    print(f"Opening {address}")
    webbrowser.open(address)

    server.serve_forever()
    server.server_close()


if __name__ == "__main__":
    main()