import socket
import os
import sys
import hashlib


HOST = "127.0.0.1"
PORT = 12000          # server port 

DOWNLOADS = "downloads"   # folder where downloaded files are saved
CHUNK = 8192              # bytes per read/send when transferring files


def send_line(sock, text):
    sock.sendall((text + "\n").encode("utf-8"))


def read_line(rfile):
    line = rfile.readline()
    if not line:
        raise ConnectionError("connection closed by server")
    return line.decode("utf-8", errors="replace").strip()


def file_md5(path):
    md5 = hashlib.md5()
    with open(path, "rb") as f:
        while True:
            data = f.read(CHUNK)
            if not data:
                break
            md5.update(data)

    return md5.hexdigest()


def do_login(sock, rfile, arg):  # satisfies LOGIN protocol in rubric
    send_line(sock, f"LOGIN {arg}")
    reply = read_line(rfile)
    print(reply)
    return reply.startswith("OK")   # returns True if server accepts login


def do_msg(sock, rfile, arg):  # empty messages are sent on purpose so the server can reject them
    send_line(sock, f"MSG {arg}")
    print(read_line(rfile))


def do_list(sock, rfile):
    send_line(sock, "LIST")
    reply = read_line(rfile)
    if not reply.startswith("OK"):
        print(reply)  # reveals potential error
        return

    count = int(reply.split()[1])
    print(f"{count} files on server:")
    for _ in range(count):
        print(" " + read_line(rfile))


def do_upload(sock, rfile, arg, logged_in):
    if not logged_in:
        print("Login required")
        return

    path = arg.strip().strip('"')
    if not path:
        print("Usage: upload <path to local file>")
        return
    if not os.path.isfile(path):
        print(f"local file not found {path}")
        return

    name = os.path.basename(path)
    size = os.path.getsize(path)
    md5 = file_md5(path)

    print(f"Uploading {name} ({size} bytes)...")
    send_line(sock, f"UPLOAD {name} {size} {md5}")
    with open(path, "rb") as f:
        while True:
            data = f.read(CHUNK)
            if not data:
                break
            sock.sendall(data)

    print(read_line(rfile))


def do_download(sock, rfile, arg):
    name = os.path.basename(arg.strip().strip('"'))
    if not name:
        print("Usage: download <filename on server>")
        return

    send_line(sock, f"DOWNLOAD {name}")
    reply = read_line(rfile)
    if not reply.startswith("OK"):
        print(reply)                             # error message
        return

    try:
        _, size_text, expected_md5 = reply.split()
        size = int(size_text)
    except ValueError:
        print("Error: malformed reply from server:", reply)
        return

    os.makedirs(DOWNLOADS, exist_ok=True)
    final_path = os.path.join(DOWNLOADS, name)
    temp_path = final_path + ".part"             

    print(f"Downloading {name} ({size} bytes)...")
    md5 = hashlib.md5()
    remaining = size
    try:
        with open(temp_path, "wb") as f:
            while remaining > 0:
                data = rfile.read(min(CHUNK, remaining))
                if not data:
                    raise ConnectionError("server disconnected during download")
                f.write(data)
                md5.update(data)
                remaining -= len(data)
    except (OSError, ConnectionError):
        if os.path.exists(temp_path):            
            os.remove(temp_path)
        raise

    if md5.hexdigest().lower() != expected_md5.lower():
        os.remove(temp_path)
        print("Error: checksum mismatch, download discarded")
        return

    os.replace(temp_path, final_path)
    print(f"Saved to {final_path} (MD5 verified)")


def show_help():
    print("Commands:")
    print("  login <username>      log in (required before anything else)")
    print("  msg <text>            send a message to the server")
    print("  list                  list files stored on the server")
    print("  upload <path>         upload a local file")
    print("  download <filename>   download a file into ./" + DOWNLOADS)
    print("  help                  show this help")
    print("  quit                  disconnect")


def main():
    host = sys.argv[1] if len(sys.argv) > 1 else HOST
    port = int(sys.argv[2]) if len(sys.argv) > 2 else PORT

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.connect((host, port))
    except OSError as e:
        print(f"Could not connect to {host}:{port}: {e}")
        return

    print(f"Connected to {host}:{port}")
    show_help()
    rfile = sock.makefile("rb")                 
    logged_in = False

    try:
        while True:
            try:
                line = input("> ").strip()
            except EOFError:
                line = "quit"
            if not line:
                continue

            parts = line.split(" ", 1)
            cmd = parts[0].lower()
            arg = parts[1].strip() if len(parts) > 1 else ""

            if cmd == "quit":
                send_line(sock, "QUIT")
                try:
                    print(read_line(rfile))
                except ConnectionError:
                    pass
                break
            elif cmd == "login":
                if do_login(sock, rfile, arg):
                    logged_in = True
            elif cmd == "msg":
                do_msg(sock, rfile, arg)
            elif cmd == "list":
                do_list(sock, rfile)
            elif cmd == "upload":
                do_upload(sock, rfile, arg, logged_in)
            elif cmd == "download":
                do_download(sock, rfile, arg)
            elif cmd == "help":
                show_help()
            else:                                # unknown command: let the server report the error
                send_line(sock, line)
                print(read_line(rfile))
    except (ConnectionError, OSError) as e:
        print("Error: connection lost:", e)
    except KeyboardInterrupt:
        print("\nDisconnecting")
    finally:
        rfile.close()
        sock.close()


if __name__ == "__main__":
    main()
