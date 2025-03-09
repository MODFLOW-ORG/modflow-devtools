from collections.abc import Iterable
from os import PathLike
from pathlib import Path


def build_table(
    caption: str,
    fpth: str | PathLike,
    arr,
    headings: Iterable[str] | None = None,
    col_widths: Iterable[float] | None = None,
):
    """
    Build a LaTeX table from the given NumPy array.

    Parameters
    ----------
    caption : str
        The table's caption
    fpth : str or path-like
        The LaTeX file to create
    arr : numpy recarray
        The array
    headings : iterable of str
        The table headings
    col_widths : iterable of float
        The table's column widths
    """

    fpth = Path(fpth).expanduser().absolute().with_suffix(".tex")

    if headings is None:
        headings = arr.dtype.names
    ncols = len(arr.dtype.names)
    label = f"tab:{fpth.stem}"

    line = get_header(caption, label, headings, col_widths=col_widths)

    for idx in range(arr.shape[0]):
        if idx % 2 != 0:
            line += "\t\t\\rowcolor{Gray}\n"
        line += "\t\t"
        for jdx, name in enumerate(arr.dtype.names):
            line += f"{arr[name][idx]}"
            if jdx < ncols - 1:
                line += " & "
        line += " \\\\\n"

    # footer
    line += get_footer()

    fpth.write_text(line)


def get_header(
    caption: str,
    label: str,
    headings: Iterable[str],
    col_widths: Iterable[float] | None = None,
    center: bool = True,
    firsthead: bool = False,
):
    """
    Build a LaTeX table header.

    Parameters
    ----------
    caption : str
        The table's caption
    label : str
        The table's label
    headings : iterable of str
        The table's heading
    col_widths : iterable of float
        The table's column widths
    center : bool
        Whether to center-align the table text
    firsthead : bool
        Whether to add first header
    """

    ncol = len(headings)
    if col_widths is None:
        dx = 0.8 / float(ncol)
        col_widths = [dx for idx in range(ncol)]
    if center:
        align = "p"
    else:
        align = "p"

    header = "\\small\n"
    header += "\\begin{longtable}[!htbp]{\n"
    for col_width in col_widths:
        header += 38 * " " + f"{align}" + f"{{{col_width}\\linewidth-2\\arraycolsep}}\n"
    header += 38 * " " + "}\n"
    header += f"\t\\caption{{{caption}}} \\label{{{label}}} \\\\\n\n"

    if firsthead:
        header += "\t\\hline \\hline\n"
        header += "\t\\rowcolor{Gray}\n"
        header += "\t"
        for idx, s in enumerate(headings):
            header += f"\\textbf{{{s}}}"
            if idx < len(headings) - 1:
                header += " & "
        header += "  \\\\\n"
        header += "\t\\hline\n"
        header += "\t\\endfirsthead\n\n"

    header += "\t\\hline \\hline\n"
    header += "\t\\rowcolor{Gray}\n"
    header += "\t"
    for idx, s in enumerate(headings):
        header += f"\\textbf{{{s}}}"
        if idx < len(headings) - 1:
            header += " & "
    header += "  \\\\\n"
    header += "\t\\hline\n"
    header += "\t\\endhead\n\n"

    return header


def get_footer():
    return "\t\\hline \\hline\n\\end{longtable}\n\\normalsize\n\n"


def exp_format(v):
    s = f"{v:.2e}"
    s = s.replace("e-0", "e-")
    s = s.replace("e+0", "e+")
    return s


def float_format(v, fmt="{:.2f}"):
    return fmt.format(v)


def int_format(v):
    return f"{v:d}"
