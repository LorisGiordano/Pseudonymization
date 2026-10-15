"""
Report of a run: warnings (burned-in annotations, skipped and failed inputs) and summary.
"""

""" FUNCTIONS """

def report(series_records: dict, skipped: list, failed: list, identifier: str, summary: str, done: str, output_root: str, link_table: str = None, maximum: int = 10,
           skipped_total: int = None, failed_total: int = None, error_log: str = None) -> None:
    """
    Print the report of a run.

    Inputs:
        - series_records: dict = linking table records of the run
        - skipped: list = inputs (files or folders) skipped because the identifier is missing (all, or examples)
        - failed: list = (input, error) of inputs that could not be processed (all, or examples)
        - identifier: str = DICOM keyword used as identifier
        - summary: str = summary line of the run
        - done: str = name of the step (e.g. 'Pseudonymization')
        - output_root: str = path to output folder
        - link_table: str = path to linking table (default = None => no linking table)
        - maximum: int = maximum number of examples printed per warning (default = 10)
        - skipped_total: int = total number of skipped inputs (default = None => len(skipped))
        - failed_total: int = total number of failed inputs (default = None => len(failed))
        - error_log: str = path to the file listing all skipped and failed inputs (default = None => no error log)
    """

    skipped_total = len(skipped) if skipped_total is None else skipped_total
    failed_total = len(failed) if failed_total is None else failed_total

    # series flagged with burned-in annotations (pixel data may contain PHI, not handled here)
    burned_in = [record['Output folder'] for record in series_records.values() if record.get('BurnedInAnnotation', '').upper() == 'YES']
    if burned_in:
        print(f"WARNING: {len(burned_in)} series flagged with BurnedInAnnotation=YES, pixel data may contain PHI "
              "(check visually or redact with the redact command), e.g.:")
        for folder in burned_in[:maximum]:
            print(" -", folder)

    # inputs that could not be processed
    if skipped_total:
        print(f"WARNING: {skipped_total} input(s) skipped because {identifier} is missing, e.g.:")
        for item in skipped[:maximum]:
            print(" -", item)
    if failed_total:
        print(f"WARNING: {failed_total} input(s) could not be processed (not written), e.g.:")
        for item, error in failed[:maximum]:
            print(" -", item, '->', error)
    if (skipped_total or failed_total) and error_log is not None:
        print(f" => all skipped and failed inputs: {error_log}")

    print(summary)
    print(f"{done} done.")
    print(" =>", output_root)
    if link_table is not None:
        print(" => linking table:", link_table)
