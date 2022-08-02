import os
import datetime

from astropy.io import fits
import numpy as np

from crds.core import rmap
from crds import data_file

from . import utils


_TIMESTAMP_FORMAT = "%b %d %Y %H:%M:%S"

_AM_PM_TIMESTAMP_FORMAT = "%b %d %Y %I:%M:%S:%f%p"

_PEDIGREE_DATE_FORMAT = "%d/%m/%Y"

_DBTABLE_BY_REFTYPE = {
    utils.THROUGHPUT_LOOKUP_REFTYPE: "CRCOMPLIST",
    utils.THERMAL_LOOKUP_REFTYPE: "CRTHERMLIST",
}

_DESCRIP_BY_REFTYPE = {
    utils.THROUGHPUT_LOOKUP_REFTYPE: "The lookup table for HST component throughputs",
    utils.THERMAL_LOOKUP_REFTYPE: "The lookup table for HST component thermal characteristics",
}

_HISTORY_DESCRIPTION_BY_REFTYPE = {
    utils.THROUGHPUT_LOOKUP_REFTYPE: "throughput",
    utils.THERMAL_LOOKUP_REFTYPE: "thermal",
}


class SynphotLookupGenerator:
    """
    Given a derived-from context and a set of newly delivered synphot files,
    produce an updated lookup file.
    """

    def __init__(self, context):
        self._context = context

    def generate(self, reftype, delivered_files):
        """
        Generate and return an HDUList containing an updated lookup table
        for the specified reftype.
        """
        # Historically ReDCaT has always set this to the current
        # local time and not UTC.
        timestamp = datetime.datetime.today().strftime(_TIMESTAMP_FORMAT)

        original_ref_path = utils.get_cache_path(
            self._context, reftype, error_on_missing=False
        )
        if original_ref_path is None:
            return self._generate_hdul(reftype, delivered_files, timestamp)
        else:
            with data_file.fits_open(original_ref_path) as original_ref:
                return self._generate_hdul(
                    reftype, delivered_files, timestamp, original_ref=original_ref
                )

    def _generate_hdul(self, reftype, delivered_files, timestamp, original_ref=None):
        if original_ref is not None:
            original_table = original_ref[-1].data
            new_time = original_table["TIME"]
            new_compname = original_table["COMPNAME"]
            new_filename = original_table["FILENAME"]
            new_comment = original_table["COMMENT"]
        else:
            new_time = np.chararray((0,), unicode=True)
            new_compname = np.chararray((0,), unicode=True)
            new_filename = np.chararray((0,), unicode=True)
            new_comment = np.chararray((0,), unicode=True)

        updated_instruments = set()
        created_instruments = set()
        for file in delivered_files:
            with data_file.fits_open(file) as hdul:
                component = hdul[0].header["COMPNAME"]
                lookup_filename = utils.get_lookup_filename(
                    component, os.path.basename(file)
                )
                description = hdul[0].header.get("DESCRIP", "")
                if component in new_compname:
                    idx = np.argwhere(new_compname == component)[0][0]
                    new_time[idx] = timestamp
                    new_filename[idx] = lookup_filename
                    new_comment[idx] = description
                    updated_instruments.add(utils.get_instrument(component))
                else:
                    new_time = np.append(new_time, timestamp)
                    new_compname = np.append(new_compname, component)
                    new_filename = np.append(new_filename, lookup_filename)
                    new_comment = np.append(new_comment, description)
                    created_instruments.add(utils.get_instrument(component))

        ind = np.argsort(new_compname)
        columns = [
            fits.Column(name="TIME", format="A26", array=new_time[ind], disp="A26"),
            fits.Column(
                name="COMPNAME", format="A18", array=new_compname[ind], disp="A18"
            ),
            fits.Column(
                name="FILENAME", format="A56", array=new_filename[ind], disp="A56"
            ),
            fits.Column(
                name="COMMENT", format="A68", array=new_comment[ind], disp="A68"
            ),
        ]

        new_table_hdu = fits.BinTableHDU.from_columns(columns)

        new_primary_hdu = fits.PrimaryHDU()
        header = new_primary_hdu.header
        header["USEAFTER"] = timestamp
        header["INSTRUME"] = "HST"
        header["COMMENT"] = "Reference file automatically generated by CRDS"
        header["DBTABLE"] = _DBTABLE_BY_REFTYPE[reftype]
        header["DESCRIP"] = _DESCRIP_BY_REFTYPE[reftype]
        header["PEDIGREE"] = self._make_pedigree(new_table_hdu)

        if original_ref:
            for item in original_ref[0].header["HISTORY"]:
                header.add_history(item)

            header.add_history(" ")
            header.add_history("Updated on {}".format(timestamp))
        else:
            header.add_history("Created on {}".format(timestamp))

        header.add_history(" ")
        self._add_instrument_history(
            reftype, header, updated_instruments, created_instruments
        )

        return fits.HDUList([new_primary_hdu, new_table_hdu])

    def _add_instrument_history(
        self, reftype, header, updated_instruments, created_instruments
    ):
        description = _HISTORY_DESCRIPTION_BY_REFTYPE[reftype]

        if len(updated_instruments) > 0:
            instrument_list = self._make_instrument_list(updated_instruments)
            header.add_history(
                "Updated {} tables for {}".format(description, instrument_list)
            )

        if len(created_instruments) > 0:
            instrument_list = self._make_instrument_list(created_instruments)
            header.add_history(
                "Created {} tables for {}".format(description, instrument_list)
            )

    def _make_instrument_list(self, instruments):
        instruments = sorted([i.upper() for i in instruments])
        if len(instruments) == 1:
            return instruments[0]
        elif len(instruments) == 2:
            return instruments[0] and instruments[1]
        else:
            return ", ".join(instruments[:-1]) + ", and " + instruments[-1]

    def _make_pedigree(self, table_hdu):
        times = [self._parse_time(t) for t in table_hdu.data["TIME"]]
        return "INFLIGHT {} {}".format(
            min(times).strftime(_PEDIGREE_DATE_FORMAT),
            max(times).strftime(_PEDIGREE_DATE_FORMAT),
        )

    def _parse_time(self, time):
        time = time.strip().lower()
        if "am" in time or "pm" in time:
            return datetime.datetime.strptime(time, _AM_PM_TIMESTAMP_FORMAT)
        else:
            return datetime.datetime.strptime(time, _TIMESTAMP_FORMAT)
