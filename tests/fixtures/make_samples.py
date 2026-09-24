from pathlib import Path


def generate_csv(dest: Path) -> None:
    header = ["id"] + [f"I{c + 1:02d}" for c in range(40)]
    lines = [",".join(header)]

    for r in range(300):
        row_id = f"P{r + 1:04d}"
        row = [row_id]
        for c in range(40):
            if (7 * r + 13 * c) % 29 == 0:
                cell = "NA" if r % 2 == 0 else ""
            else:
                cell = "1" if (r + 2 * c) % 5 != 0 else "0"
            row.append(cell)
        lines.append(",".join(row))

    dest.write_text("\n".join(lines) + "\n", encoding="utf-8")


def generate_prn(dest: Path) -> None:
    lines = []
    for r in range(60):
        label = f"P{r + 1:04d}".ljust(8)
        items = []
        for c in range(20):
            if (11 * r + 5 * c) % 23 == 0:
                char = " " if r % 2 == 0 else "X"
            else:
                char = "A" if (r + c) % 2 == 0 else "B"
            items.append(char)
        lines.append(f"{label}  {''.join(items)}")

    dest.write_text("\n".join(lines) + "\n", encoding="utf-8")


def generate_con(dest: Path) -> None:
    content = (
        "&INST\n"
        "ITEM1 = 11\n"
        "NI = 20\n"
        "NAMLEN = 8\n"
        "NAME1 = 1\n"
        "KEY1 = ABABABABABABABABABAB\n"
        "CODES = AB\n"
        "DATA = sample_winsteps.prn\n"
        "&END\n"
    )
    dest.write_text(content, encoding="utf-8")


def main() -> None:
    fixture_dir = Path(__file__).resolve().parent
    generate_csv(fixture_dir / "sample_300x40.csv")
    generate_prn(fixture_dir / "sample_winsteps.prn")
    generate_con(fixture_dir / "sample_winsteps.CON")


if __name__ == "__main__":
    main()
