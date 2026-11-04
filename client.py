import socket
import os
import hashlib


HOST = ""                  # "" means listen on all network interfaces
PORT = 12000               # any free port above 1024; the client must use the same one

STORAGE = "server_files"   # folder where uploaded files are kept
CHUNK = 8192               # bytes per read/send when transferring files


def send_line(conn, text):                      # send one line of text to the client
    conn.sendall((text + "\n").encode("utf-8")) 


def send_error(conn, reason):                   # show an error on the server screen and send ERR <reason> to the client
    print(f"Error: {reason}")
    send_line(conn, f"ERR {reason}")


def safe_filename(name):                       # keep only the base name so files can't be written outside STORAGE
    name = os.path.basename(name.strip())
    if name in ("", ".", ".."):
        return None
    return name


def receive_file(rfile, size, path):           # read exactly `size` bytes from the client into `path`.
    md5 = hashlib.md5()
    remaining = size

    with open(path, "wb") as f:
        while remaining > 0:
            data = rfile.read(min(CHUNK, remaining))

            if not data:
                raise ConnectionError("client disconnected during upload")
            f.write(data)
            md5.update(data)
            remaining -= len(data)

    return md5.hexdigest()


def discard_bytes(rfile, size):                # read and throw away `size` bytes, so they aren't mistaken for commands
    remaining = size
    while remaining > 0:
        data = rfile.read(min(CHUNK, remaining))
        if not data:
            raise ConnectionError("client disconnected during upload")
        remaining -= len(data)


def file_md5(path):                           # MD5 hash of a file on disk, read in chunks.
    md5 = hashlib.md5()
    with open(path, "rb") as f:

        while True:
            data = f.read(CHUNK)
            if not data:
                break
            md5.update(data)

    return md5.hexdigest()


def handle_upload(conn, rfile, arg):         # Expected: UPLOAD <filename> <size> <md5>  (filename may contain spaces)
    pieces = arg.rsplit(" ", 2)
    if len(pieces) != 3 or not pieces[1].isdigit():
        send_error(conn, "Invalid command")
        return
    raw_name, size_text, expected_md5 = pieces
    size = int(size_text)

    name = safe_filename(raw_name)
    if name is None:
        discard_bytes(rfile, size)           # client sends the bytes anyway
        send_error(conn, "Invalid filename")
        return

    final_path = os.path.join(STORAGE, name)
    temp_path = final_path + ".part"         # don't touch the real file until verified

    print(f"Receiving file: {name} ({size} bytes)")
    try:
        actual_md5 = receive_file(rfile, size, temp_path)
    except OSError:
        if os.path.exists(temp_path):        # don't leave half a file behind
            os.remove(temp_path)
        raise                                # main() prints the error

    if actual_md5.lower() != expected_md5.lower():
        os.remove(temp_path)
        send_error(conn, "Checksum mismatch")
        return

    if os.path.exists(final_path):
        print(f"Overwriting existing file: {name}")
    os.replace(temp_path, final_path)
    print(f"File received: {name} ({size} bytes, MD5 verified)")
    send_line(conn, f"OK uploaded {name}")


def handle_download(conn, arg):            # Expected: DOWNLOAD <filename>  
    name = safe_filename(arg)
    if name is None:
        send_error(conn, "Invalid filename")
        return

    path = os.path.join(STORAGE, name)
    if not os.path.isfile(path):
        send_error(conn, "File not found")
        return

    size = os.path.getsize(path)
    send_line(conn, f"OK {size} {file_md5(path)}")
    with open(path, "rb") as f:
        while True:
            data = f.read(CHUNK)
            if not data:
                break
            conn.sendall(data)
    print(f"File sent: {name} ({size} bytes)")


def handle_client(conn):                 # talk to one connected client until they disconnect.
    rfile = conn.makefile("rb")          # buffered reader: readline() / read(n)
    logged_in = False                    # client must LOGIN first
    try:
        while True:
            line = rfile.readline()
            if not line:                 # b"" means the client disconnected
                break
            command = line.decode("utf-8", errors="replace").strip()
            print("Received:", command)

            parts = command.split(" ", 1)
            cmd = parts[0].upper()
            arg = parts[1] if len(parts) > 1 else ""

            if cmd == "QUIT":
                send_line(conn, "OK Bye")
                break

            elif cmd == "LOGIN":
                try:
                    with open("users.txt") as f:
                        valid_users = [n.strip() for n in f.read().splitlines() if n.strip()]
                except FileNotFoundError:
                    print("Error: users.txt not found")
                    valid_users = []

                if arg in valid_users:
                    logged_in = True
                    print(f"User logged in: {arg}")
                    send_line(conn, f"OK Welcome {arg}")
                else:
                    send_error(conn, "Unknown user")

            elif not logged_in:
                send_error(conn, "Not logged in")

            elif cmd == "MSG":
                if not arg.strip():
                    send_error(conn, "Empty message")
                else:
                    print(f"Message received: {arg}")
                    send_line(conn, "OK Message Received")

            elif cmd == "LIST":
                files = sorted(n for n in os.listdir(STORAGE)
                               if os.path.isfile(os.path.join(STORAGE, n))
                               and not n.endswith(".part"))
                send_line(conn, f"OK {len(files)}")
                for name in files:
                    send_line(conn, name)

            elif cmd == "UPLOAD":
                handle_upload(conn, rfile, arg)

            elif cmd == "DOWNLOAD":
                handle_download(conn, arg)

            else:
                send_error(conn, "Invalid command")
    finally:
        rfile.close()


def main():
    os.makedirs(STORAGE, exist_ok=True)

    try:
        hostname = socket.gethostname()
        ip = socket.gethostbyname(hostname)
        print(f"Hostname: {hostname}")
        print(f"IP: {ip}")
    except socket.gaierror:
        print("Could not look up this computer's IP address")

    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)    # TCP socket
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)  # quick restarts
    listener.bind((HOST, PORT))
    listener.listen(1)
    print(f"Server listening on port {PORT}")

    try:
        while True:                                  # run until Ctrl+C
            conn, addr = listener.accept()           # wait for a client
            print("Client connected:", addr)
            try:
                handle_client(conn)
                print("Client disconnected:", addr)
            except OSError as e:                     # e.g. client vanished
                print("Error: connection lost:", e)
            finally:
                conn.close()                         # then wait for the next one
    except KeyboardInterrupt:
        print("\nServer shutting down")
    finally:
        listener.close()


if __name__ == "__main__":
    main()
