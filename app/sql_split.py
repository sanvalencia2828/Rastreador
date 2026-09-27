"""Split a SQL script on semicolons that are not inside quotes or comments."""


def split_sql(script: str) -> list[str]:
    parts: list[str] = []
    buf: list[str] = []
    i = 0
    n = len(script)
    while i < n:
        ch = script[i]
        nxt = script[i + 1] if i + 1 < n else ""

        if ch == "-" and nxt == "-":
            end = script.find("\n", i)
            if end == -1:
                buf.append(script[i:])
                break
            buf.append(script[i : end + 1])
            i = end + 1
            continue

        if ch == "/" and nxt == "*":
            end = script.find("*/", i + 2)
            if end == -1:
                buf.append(script[i:])
                break
            buf.append(script[i : end + 2])
            i = end + 2
            continue

        if ch == "'":
            buf.append(ch)
            i += 1
            while i < n:
                buf.append(script[i])
                if script[i] == "'" and (i + 1 >= n or script[i + 1] != "'"):
                    i += 1
                    break
                if script[i] == "'" and i + 1 < n and script[i + 1] == "'":
                    buf.append(script[i + 1])
                    i += 2
                    continue
                i += 1
            continue

        if ch == "$":
            end_tag = script.find("$", i + 1)
            if end_tag != -1 and "\n" not in script[i : end_tag + 1] and all(
                c.isalnum() or c == "_" or c == "$" for c in script[i : end_tag + 1]
            ):
                tag = script[i : end_tag + 1]
                close = script.find(tag, end_tag + 1)
                if close != -1:
                    buf.append(script[i : close + len(tag)])
                    i = close + len(tag)
                    continue
            buf.append(ch)
            i += 1
            continue

        if ch == ";":
            statement = "".join(buf).strip()
            if statement:
                parts.append(statement)
            buf = []
            i += 1
            continue

        buf.append(ch)
        i += 1

    tail = "".join(buf).strip()
    if tail:
        parts.append(tail)
    return parts
