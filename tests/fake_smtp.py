import base64
import socketserver
import threading


class FakeSmtp:
    """Minimal SMTP server that records messages and the credentials it was given."""

    def __init__(self, accept_password="right-password"):
        self.messages, self.logins = [], []
        outer = self

        class Handler(socketserver.StreamRequestHandler):
            def reply(self, text):
                self.wfile.write(text.encode() + b"\r\n")

            def handle(self):
                self.reply("220 fake ESMTP")
                sender, recipients = "", []
                while line := self.rfile.readline():
                    command = line.decode().strip()
                    verb = command.split(" ")[0].upper()
                    if verb == "EHLO":
                        self.wfile.write(b"250-fake\r\n250 AUTH PLAIN\r\n")
                    elif verb == "AUTH":
                        _, user, password = base64.b64decode(command.split(" ")[2]).decode().split("\0")
                        outer.logins.append((user, password))
                        self.reply("235 ok" if password == accept_password else "535 bad credentials")
                    elif verb == "MAIL":
                        sender, recipients = command[10:].strip("<>"), []
                        self.reply("250 ok")
                    elif verb == "RCPT":
                        recipients.append(command[8:].strip("<>"))
                        self.reply("250 ok")
                    elif verb == "DATA":
                        self.reply("354 go")
                        body = b""
                        while (chunk := self.rfile.readline()) != b".\r\n":
                            body += chunk
                        outer.messages.append((sender, recipients, body.decode()))
                        self.reply("250 queued")
                    elif verb == "QUIT":
                        self.reply("221 bye")
                        return
                    else:
                        self.reply("250 ok")

        self.server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def stop(self):
        self.server.shutdown()
        self.server.server_close()
