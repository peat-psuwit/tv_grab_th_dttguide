#!/usr/bin/env python3

# XMLTV grabber for Thailand's DTT Guide, an application and a website
# from NBTC. The APIs are reversed-engineered from the website version.
#
# Copyright (C) 2025-, Ratchanan Srirattanamet <peathot@hotmail.com>
# SPDX-License-Identifier: GPL-3.0-or-later

import sys
import xml.etree.ElementTree as ET

from datetime import datetime, timedelta, timezone
from enum import Enum

import requests


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

    def getJson(self, action: str, channel_type: ChannelType) -> dict:
        url = f"{DTTGuide.BASE_URL}/{action}"
        data = {"channelType": f"{channel_type.value}"}

        res = self.req_session.post(url, json=data)
        return res.json()

    def getProgramDataWeb(self, channel_type: ChannelType) -> list[dict[str, str]]:
        res_json = self.getJson("getProgramDataWeb", channel_type)
        return res_json["results"]

    def getChannelNameWeb(self, channel_type: ChannelType) -> list[dict[str, str]]:
        res_json = self.getJson("getChannelNameWeb", channel_type)
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
    timezone_thai = timezone(timedelta(hours=7))
    ret: list[ET.Element] = []

    for program in program_data:
        start = datetime.strptime(
            f"{program['pgDate']} {program['pgBeginTime']}", "%d-%m-%y %H:%M:%S"
        ).replace(tzinfo=timezone_thai)
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


def main(argv):
    # TODO: parse args for TV grabber flags
    # TODO: parse channel type from args
    channel_type = DTTGuide.ChannelType.NATIONAL

    dtt_guide = DTTGuide()

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
            dtt_guide.getChannelNameWeb(channel_type),
            dtt_guide.getChannelLogoMediaWeb(channel_type),
            {
                # No one calls ThaiPBS "องค์การกระจายเสียงและแพร่ภาพสาธารณะแห่งประเทศไทย"
                "03": "ThaiPBS",
                "27": "ช่อง 8",
            },
        )
    )

    e_tv.extend(programme_from_programdata(dtt_guide.getProgramDataWeb(channel_type)))

    tree = ET.ElementTree(e_tv)
    tree.write(sys.stdout, encoding="unicode")


if __name__ == "__main__":
    main(sys.argv)
