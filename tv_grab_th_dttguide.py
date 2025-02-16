#!/usr/bin/env python3

# XMLTV grabber for Thailand's DTT Guide, an application and a website
# from NBTC. The APIs are reversed-engineered from the website version.
#
# Copyright (C) 2025-, Ratchanan Srirattanamet <peathot@hotmail.com>
# SPDX-License-Identifier: GPL-3.0-or-later

import argparse
import sys
import xml.etree.ElementTree as ET

from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Optional, TextIO

import requests

TZ_THAI = timezone(timedelta(hours=7))


class DTTGuide:
    """
    Internal API for https://dttguide.nbtc.go.th/dttguide/
    WARNING: Reverse-engineered.
    WARNING: No error handling.
    """

    class ChannelType(Enum):
        NATIONAL = 1
        LOCAL = 2

    BASE_URL = "https://dttguide.nbtc.go.th/BcsEpgDataServices/BcsEpgDataController"

    req_session = requests.Session()

    def __init__(self):
        self.req_session.headers.update(
            {"content-type": "application/json; charset=utf-8"}
        )

    def getJson(self, action: str, channel_type: Optional[ChannelType] = None) -> dict:
        url = f"{DTTGuide.BASE_URL}/{action}"
        if channel_type is not None:
            data = {"channelType": f"{channel_type.value}"}
        else:
            data = None

        res = self.req_session.post(url, json=data)
        return res.json()

    def getProgramDataWeb(self, channel_type: ChannelType) -> list[dict[str, str]]:
        res_json = self.getJson("getProgramDataWeb", channel_type)
        return res_json["results"]

    def getChannelNameWeb(self) -> list[dict[str, str]]:
        res_json = self.getJson("getChannelNameWeb")
        return res_json["results"]

    def getChannelLogoMediaWeb(self, channel_type: ChannelType) -> list[dict[str, str]]:
        res_json = self.getJson("getChannelLogoMediaWeb", channel_type)
        return res_json["channelLogoMediaImage"]


def channels_from_chnames_and_chlogos(
    chnames: list[dict[str, str]],
    chlogos: list[dict[str, str]],
    dispname_exceptions: dict[str, str],
) -> list[ET.Element]:
    ret: list[ET.Element] = []

    for ch in chnames:
        e_channel = ET.Element(
            "channel",
            {
                # XXX: please suggest a better way for id.
                "id": f"{ch["channelNo"]}.dttguide.nbtc.go.th",
            },
        )

        try:
            ET.SubElement(e_channel, "display-name", {"lang": "th"}).text = (
                dispname_exceptions[ch["channelNo"]]
            )
        except KeyError:
            pass

        ET.SubElement(e_channel, "display-name", {"lang": "th"}).text = ch["stnName"]

        if ch["stnNickname"] != ch["stnName"]:
            ET.SubElement(e_channel, "display-name", {"lang": "th"}).text = ch[
                "stnNickname"
            ]

        for logo in chlogos:
            if logo["channelNo"] == ch["channelNo"]:
                ET.SubElement(
                    e_channel,
                    "icon",
                    {
                        # XXX: I have no idea if data URL is supported.
                        "src": f"data:image/png;base64,{logo["channelLogoImage"]}"
                    },
                )

                break

        ret.append(e_channel)

    return ret


def parse_duration(pgDuration: str):
    hours, minutes, seconds = pgDuration.split(":")
    return timedelta(hours=float(hours), minutes=float(minutes), seconds=float(seconds))


def programme_from_programdata(program_data: list[dict[str, str]]) -> list[ET.Element]:
    ret: list[ET.Element] = []

    for program in program_data:
        start = datetime.strptime(
            f"{program['pgDate']} {program['pgBeginTime']}", "%d-%m-%y %H:%M:%S"
        ).replace(tzinfo=TZ_THAI)
        stop = start + parse_duration(program["pgDuration"])

        e_programme = ET.Element(
            "programme",
            {
                # Match channel entry above.
                "channel": f"{program["channelNo"]}.dttguide.nbtc.go.th",
                "start": start.strftime("%Y%m%d%H%M%S %z"),
                "stop": stop.strftime("%Y%m%d%H%M%S %z"),
            },
        )

        ET.SubElement(e_programme, "title", {"lang": "th"}).text = program["pgTitle"]
        if program["pgDesc"] is not None:
            ET.SubElement(e_programme, "desc", {"lang": "th"}).text = program["pgDesc"]

        # TODO: a way to express audioDescFlag, multiLangFlag in XMLTV.
        # TODO: what is subTitleFlag exactly?

        if program["closeCaptFlag"] == "Y":
            ET.SubElement(e_programme, "subtitles", {"type": "teletext"})
        if program["signLangFlag"] == "Y":
            ET.SubElement(e_programme, "subtitles", {"type": "deaf-signed"})

        ret.append(e_programme)

    return ret


# Return whether data covers [earliest_start, latest_start_exclusive)
# TODO: split this function into 4 (fetch(?), filter, convert, is_cover_days)
def fetch_filter_convert(
    outfile: TextIO,
    earliest_start: Optional[datetime],
    latest_start_exclusive: Optional[datetime],
) -> bool:
    dtt_guide = DTTGuide()

    chnames = dtt_guide.getChannelNameWeb()
    chlogos = dtt_guide.getChannelLogoMediaWeb(
        DTTGuide.ChannelType.NATIONAL
    ) + dtt_guide.getChannelLogoMediaWeb(DTTGuide.ChannelType.LOCAL)
    program_data = dtt_guide.getProgramDataWeb(
        DTTGuide.ChannelType.NATIONAL
    ) + dtt_guide.getProgramDataWeb(DTTGuide.ChannelType.LOCAL)

    def whithin_start_dates(program):
        start = datetime.strptime(
            f"{program['pgDate']} {program['pgBeginTime']}", "%d-%m-%y %H:%M:%S"
        ).replace(tzinfo=TZ_THAI)

        if earliest_start is not None and start < earliest_start:
            return False

        if latest_start_exclusive is not None and start >= latest_start_exclusive:
            return False

        return True

    program_data = list(filter(whithin_start_dates, program_data))

    channels_with_program: set[str] = set()
    for program in program_data:
        channels_with_program.add(program["channelNo"])

    chnames = list(filter(lambda ch: ch["channelNo"] in channels_with_program, chnames))

    e_tv = ET.Element(
        "tv",
        {
            "source-info-name": "DTT Guide",
            "source-info-url": "https://dttguide.nbtc.go.th/dttguide/",
            "generator-info-name": "tv_grab_th_dttguide",
            "generator-info-url": "https://github.com/peat-psuwit/tv_grab_th_dttguide",
        },
    )

    e_tv.extend(
        channels_from_chnames_and_chlogos(
            chnames,
            chlogos,
            {
                # No one calls ThaiPBS "องค์การกระจายเสียงและแพร่ภาพสาธารณะแห่งประเทศไทย"
                "03": "ThaiPBS",
                "27": "ช่อง 8",
            },
        )
    )
    e_tv.extend(programme_from_programdata(program_data))

    tree = ET.ElementTree(e_tv)
    tree.write(outfile, encoding="unicode", xml_declaration=True)

    # Determine whether program_data covers [earliest_start, latest_start_exclusive)

    if earliest_start is None or latest_start_exclusive is None:
        return True

    covers_earliest_start = False
    covers_latest_start_exclusive = False
    for program in program_data:
        start = datetime.strptime(
            f"{program['pgDate']} {program['pgBeginTime']}", "%d-%m-%y %H:%M:%S"
        ).replace(tzinfo=TZ_THAI)

        if start - earliest_start < timedelta(hours=24):
            covers_earliest_start = True

        if latest_start_exclusive - start < timedelta(hours=24):
            covers_latest_start_exclusive = True

        if covers_earliest_start and covers_latest_start_exclusive:
            return True

    return False


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="tv_grab_th_dttguide", description="XMLTV grabber for Thailand's DTT Guide"
    )
    parser.add_argument("--version", action="store_true")
    # https://wiki.xmltv.org/index.php/XmltvCapabilities
    parser.add_argument("--description", action="store_true")
    parser.add_argument("--capabilities", action="store_true")
    # "baseline" capabilities
    # We don't output anything anyway.
    parser.add_argument("--quiet", action="store_true")
    parser.add_argument("--output", help="Output file, default to standard output.")
    parser.add_argument("--days", type=int)
    parser.add_argument("--offset", type=int)
    # We offer no configurability.
    parser.add_argument("--config-file")

    args = parser.parse_args()

    if args.version:
        print("0.0~dev")
        return 0

    if args.description:
        print("Thailand (https://dttguide.nbtc.go.th/dttguide)")
        return 0

    if args.capabilities:
        print("baseline")
        return 0

    outfile = sys.stdout
    if args.output is not None:
        outfile = open(args.output, "w")

    earliest_start: Optional[datetime] = None
    latest_start_exclusive: Optional[datetime] = None

    # XXX: should we provide historical data in absence of either flags?
    if args.offset is not None:
        earliest_start = datetime.now(TZ_THAI).replace(
            hour=0, minute=0, second=0, microsecond=0
        ) + timedelta(days=args.offset)

    if args.days is not None:
        if earliest_start is None:
            earliest_start = datetime.now(TZ_THAI).replace(
                hour=0, minute=0, second=0, microsecond=0
            )

        latest_start_exclusive = earliest_start + timedelta(days=args.days)

    covers_days = fetch_filter_convert(outfile, earliest_start, latest_start_exclusive)

    if covers_days:
        return 0
    else:
        print(
            "Warning: DTTGuide doesn't provide enough data for requested amount of days.",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
