"""
Report of a run: warnings (burned-in annotations, skipped and failed inputs) and summary.
"""

""" FUNCTIONS """

def report(series_records: dict, skipped: list, failed: list, identifier: str, summary: str, done: str, output_root: str, link_table: str, maximum: int = 10) -> None:
    """
    Print the report of a run.

    Inputs:
        - series_records: dict = linking table records of the run
        - skipped: list = inputs (files or folders) skipped because the identifier is missing
        - failed: list = (input, error) of inputs that could not be processed
        - identifier: str = DICOM keyword used as identifier
        - summary: str = summary line of the run
        - done: str = name of the step (e.g. 'Pseudonymization')
        - output_root: str = path to output folder
        - link_table: str = path to linking table
        - maximum: int = maximum number of examples printed per warning (default = 10)
    """

    # series flagged with burned-in annotations (pixel data may contain PHI, not handled here)
    burned_in = [record['Output folder'] for record in series_records.values() if record.get('BurnedInAnnotation', '').upper() == 'YES']
    if burned_in:
        print(f"WARNING: {len(burned_in)} series flagged with BurnedInAnnotation=YES, pixel data may contain PHI "
              "(check visually or redact with presidio.py), e.g.:")
        for folder in burned_in[:maximum]:
            print(" -", folder)

    # inputs that could not be processed
    if skipped:
        print(f"WARNING: {len(skipped)} input(s) skipped because {identifier} is missing, e.g.:")
        for item in skipped[:maximum]:
            print(" -", item)
    if failed:
        print(f"WARNING: {len(failed)} input(s) could not be processed (not written), e.g.:")
        for item, error in failed[:maximum]:
            print(" -", item, '->', error)

    print(summary)
    print(f"{done} done.")
    print(" =>", output_root)
    print(" => linking table:", link_table)
