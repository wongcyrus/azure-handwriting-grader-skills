"""Remove the retired, managed banner appendix without changing article prose."""


START = "<!-- BEGIN BANNER WALKTHROUGH -->"
END = "<!-- END BANNER WALKTHROUGH -->"


def without_banner_appendix(text):
    if START not in text and END not in text:
        return text
    if text.count(START) != 1 or text.count(END) != 1:
        raise ValueError("Unexpected banner appendix markers")
    before, remainder = text.split(START, 1)
    _, after = remainder.split(END, 1)
    return before.rstrip() + "\n" + after
