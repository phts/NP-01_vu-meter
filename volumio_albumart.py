# Copyright 2021 PeppyMeter for Volumio by 2aCD
#
# This file is part of PeppyMeter for Volumio
#

import time
import os.path
import pygame as pg
import requests
import io
import ctypes
import logging
import traceback

try:
    import cairosvg
    from PIL import Image
except:
    pass  # if it not properly installed

from socketIO_client import SocketIO
from threading import Thread, Timer
from configparser import ConfigParser

from configfileparser import METER, EXIT_TIMEOUT
from volumio_configfileparser import (
    ALBUMART_POS,
    ALBUMART_DIM,
    ALBUMBORDER,
    PLAY_ANIMATION,
    PLAY_TITLE_POS,
    PLAY_ARTIST_POS,
    PLAY_ALBUM_POS,
    PLAY_CENTER,
    PLAY_MAX,
    FONTSIZE_LIGHT,
    FONTSIZE_REGULAR,
    FONTSIZE_BOLD,
    FONTCOLOR,
    PLAY_TITLE_STYLE,
    PLAY_ARTIST_STYLE,
    PLAY_ALBUM_STYLE,
    FONT_STYLE_L,
    FONT_STYLE_R,
    FONT_STYLE_B,
    FONT_PATH,
    FONT_LIGHT,
    FONT_REGULAR,
    FONT_BOLD,
    TIME_REMAINING_POS,
    FONTSIZE_DIGI,
    TIMECOLOR,
    PLAY_TYPE_POS,
    PLAY_TYPE_COLOR,
    PLAY_TYPE_DIM,
    PLAY_SAMPLE_POS,
    PLAY_SAMPLE_STYLE,
    PLAY_SAMPLE_RIGHT,
    EXTENDED_CONF,
    TIME_TYPE,
)


class AlbumartAnimator(Thread):
    """Provides show albumart in a separate thread"""

    def __init__(self, util, meter_config_volumio, base, pm):
        """Initializer

        :param util: utility class
        :param base: complete meter class
        """
        Thread.__init__(self)
        self.screen = util.PYGAME_SCREEN
        self.base = base
        self.run_flag = True
        self.util = util
        self.meter_config = util.meter_config
        self.meter_config_volumio = meter_config_volumio
        self.meter_section = meter_config_volumio[self.meter_config[METER]]
        self.pm = pm
        self.exit_timer = None

    def run(self):
        """Thread method. show all title infos and albumart."""
        try:

            def on_push_state(*args):
                self.pm.set_volume(args[0]["volume"])
                status = args[0]["status"]
                if status == "play":
                    if self.exit_timer is not None:
                        self.exit_timer.cancel()
                        self.exit_timer = None
                    if self.meter_section[EXTENDED_CONF] == True:
                        # draw albumart
                        if args[0]["albumart"] != self.albumart_mem:
                            self.albumart_mem = args[0]["albumart"]
                            title_factory.get_albumart_data(self.albumart_mem)
                            title_factory.render_aa(self.first_run)

                        # draw title info
                        title_factory.get_title_data(args[0])
                        title_factory.render_text(self.first_run)

                        # draw reamining time, timer is started for countdown
                        if self.meter_section[TIME_REMAINING_POS]:
                            duration = args[0]["duration"] if "duration" in args[0] else 0
                            seek = args[0]["seek"] if "seek" in args[0] and args[0]["seek"] is not None else 0
                            service = args[0]["service"] if "service" in args[0] else ""
                            self.time_args = [duration, seek, service]

                            # repeat timer start, initial with duration and seek -> remaining_time
                            try:
                                self.timer_initial = True
                                timer.start()
                            except:
                                pass

                        self.first_run = False
                    self.status_mem = "play"

                elif (status == "pause" or status == "stop") and self.status_mem == "play":
                    self.status_mem = status

                    def exit_vu():
                        pg.event.post(pg.event.Event(pg.MOUSEBUTTONUP))

                    if self.meter_config[EXIT_TIMEOUT] == 0:
                        exit_vu()
                    else:
                        timer.cancel()
                        self.exit_timer = Timer(self.meter_config[EXIT_TIMEOUT] / 1000, exit_vu)
                        self.exit_timer.start()

                else:
                    self.status_mem = "other"

            def remaining_time():
                time = title_factory.get_time_data(self.time_args, self.timer_initial)
                title_factory.render_time(time, self.first_run_digi)
                self.timer_initial = False
                self.first_run_digi = False

            def counter():
                counter = title_factory.get_counter_data(self.time_args, self.timer_initial)
                title_factory.render_time(counter, self.first_run_digi)
                self.timer_initial = False
                self.first_run_digi = False

            def on_connect():
                socketIO.on("pushState", on_push_state)
                socketIO.emit("getState", "", on_push_state)

            self.albumart_mem = ""
            self.status_mem = "pause"
            self.first_run = True
            self.first_run_digi = True
            time_type = self.meter_section[TIME_TYPE]
            timer = RepeatTimer(1, counter if time_type == "counter" else remaining_time)

            if self.meter_section[EXTENDED_CONF] == True:
                title_factory = ImageTitleFactory(self.util, self.base, self.meter_config_volumio)
                title_factory.load_fonts()  # load fonts for title info
            else:
                title_factory = None

            socketIO = SocketIO("localhost", 3000)
            socketIO.once("connect", on_connect)

            # wait while run_flag true
            while self.run_flag:
                socketIO.wait(1)

            # on exit
            socketIO.disconnect()
            if self.meter_section[EXTENDED_CONF] == True:
                title_factory.stop_text_animator()
                timer.cancel()
                del timer
                time.sleep(1)

            cleanup_memory()
        except Exception as e:
            logging.error(traceback.format_exc())
            cleanup_memory()

    def cleanup_memory(self):
        del title_factory
        del self.screen
        del self.base
        del self.util
        del self.meter_config
        del socketIO
        self.trim_memory()

    def stop_thread(self):
        """Stop thread"""

        self.run_flag = False
        time.sleep(1)

    # cleanup memory on exit
    def trim_memory(self) -> int:
        libc = ctypes.CDLL("libc.so.6")
        return libc.malloc_trim(0)


# ===================================================================================================================
class ImageTitleFactory:
    """Provides show albumart in a separate thread"""

    def __init__(self, util, base, meter_config_volumio):
        """Initializer

        :param util: utility class
        :param ui_refresh_period
        """

        self.screen = util.PYGAME_SCREEN
        self.util = util
        self.meter_config = meter_config_volumio
        # self.config = ConfigParser()
        self.meter_section = meter_config_volumio[util.meter_config[METER]]
        self.base = base
        self.titleMem = ""

    def load_fonts(self):
        """load fonts for titleinfo"""
        FontPath = self.meter_config[FONT_PATH]
        FontPathDigi = os.path.dirname(os.path.realpath(__file__)) + "/fonts/DSEG7Classic-Italic.ttf"

        # font style light
        self.fontL = None
        if os.path.exists(FontPath + self.meter_config[FONT_LIGHT]):
            self.fontL = pg.font.Font(FontPath + self.meter_config[FONT_LIGHT], self.meter_section[FONTSIZE_LIGHT])
        else:
            self.fontL = pg.font.SysFont(None, 50)

        # font style regular
        self.fontR = None
        if os.path.exists(FontPath + self.meter_config[FONT_REGULAR]):
            self.fontR = pg.font.Font(FontPath + self.meter_config[FONT_REGULAR], self.meter_section[FONTSIZE_REGULAR])
        else:
            self.fontR = pg.font.SysFont(None, 50)

        # font style bold
        self.fontB = None
        if os.path.exists(FontPath + self.meter_config[FONT_BOLD]):
            self.fontB = pg.font.Font(FontPath + self.meter_config[FONT_BOLD], self.meter_section[FONTSIZE_BOLD])
        else:
            self.fontB = pg.font.SysFont(None, 70)

        # digital font for remaining time
        self.FontDigi = None
        if os.path.exists(FontPathDigi) and self.meter_section[FONTSIZE_DIGI]:
            self.fontDigi = pg.font.Font(FontPathDigi, self.meter_section[FONTSIZE_DIGI])
        else:
            self.fontDigi = pg.font.SysFont(None, 40)

        self.fontcolor = self.meter_section[FONTCOLOR]
        # green = (84, 198, 136)

    # get data functions
    # ----------------------------------
    def get_title_data(self, play_info):
        """get title infos from argument"""
        if hasattr(self, "playinfo_title"):
            self.titleMem = self.playinfo_title
        self.playinfo_title = play_info["title"] if play_info["title"] is not None else ""
        self.playinfo_artist = play_info["artist"] if "artist" in play_info and play_info["artist"] is not None else ""
        self.playinfo_album = play_info["album"] if "album" in play_info and play_info["album"] is not None else ""
        self.playinfo_trackT = play_info["trackType"] if play_info["trackType"] is not None else ""
        self.playinfo_sample = str(play_info["samplerate"]) if "samplerate" in play_info and play_info["samplerate"] is not None else ""
        self.playinfo_depth = play_info["bitdepth"] if "bitdepth" in play_info and play_info["bitdepth"] is not None else ""
        self.playinfo_pos = (
            str(play_info["position"] + 1).rjust(2, "0") + " - "
            if self.playinfo_trackT != "webradio"
            and self.playinfo_trackT != "Podcast"
            and "position" in play_info
            and play_info["position"] is not None
            else ""
        )
        self.playinfo_tracknumber = "tracknumber" in play_info and play_info["tracknumber"] is not None
        self.playinfo_bitrate = play_info["bitrate"] if "bitrate" in play_info and play_info["bitrate"] is not None else ""
        self.playinfo_year = play_info["year"] if "year" in play_info and play_info["year"] is not None else ""
        duration_sec = play_info["duration"] if "duration" in play_info else None
        duration_time = "%02d:%02d" % (duration_sec / 60, duration_sec % 60) if duration_sec is not None else ""
        self.playinfo_duration = (duration_time + "/" + str(duration_sec)) if duration_sec is not None else ""
        if not self.meter_section[PLAY_ALBUM_POS] and self.playinfo_album != "":
            self.playinfo_artist = self.playinfo_artist + " - " + self.playinfo_album
        if self.playinfo_trackT == "dsf":
            self.playinfo_trackT = "dsd"

    def get_albumart_data(self, play_info):
        try:
            albumart = play_info
            if len(albumart) == 0:
                albumart = "http://localhost:3000/albumart"
            if "http" not in albumart:
                albumart = "http://localhost:3000" + play_info

            response = requests.get(albumart)
            self.aa_img = None
            self.aa_img = pg.image.load(io.BytesIO(response.content))
            if self.meter_section[ALBUMART_DIM]:
                self.aa_img = pg.transform.scale(self.aa_img, self.meter_section[ALBUMART_DIM])
        except:
            self.aa_img = None

    def get_time_data(self, time_args, timer_init):
        if time_args[2] == "webradio":
            return "--:--"
        seek_current = int(float(time_args[1]) / 1000)
        self.seek_new = seek_current if timer_init else self.seek_new + 1
        r = time_args[0] - self.seek_new
        if r <= 0:
            r = 0
        return "{:02d}:{:02d}".format(r // 60, r % 60)

    def get_counter_data(self, time_args, timer_init):
        if time_args[2] == "webradio":
            return "---"
        seek_current = int(float(time_args[1]) / 1000)
        self.seek_new = seek_current if timer_init else self.seek_new + 1
        if self.seek_new > 999:
            self.seek_new = self.seek_new % 1000
        return "{:03d}".format(self.seek_new)

    # render data functions
    # ----------------------------------
    def render_aa(self, firstrun):
        """render albumart"""

        if self.meter_section[ALBUMART_POS]:
            aa_rect = pg.Rect(
                self.meter_section[ALBUMART_POS][0],
                self.meter_section[ALBUMART_POS][1],
                self.meter_section[ALBUMART_DIM][0],
                self.meter_section[ALBUMART_DIM][1],
            )
            if firstrun:  # backup clean area on first run
                self.AABackup = None
                self.AABackup = self.screen.subsurface(aa_rect).copy()
            self.screen.blit(self.AABackup, aa_rect)
            self.screen.blit(self.aa_img, aa_rect)  # draw albumart
            if self.meter_section[ALBUMBORDER]:
                pg.draw.rect(self.screen, self.fontcolor, aa_rect, self.meter_section[ALBUMBORDER])  # draw border
            # update albumart rectangle
            self.base.update_rectangle(aa_rect)

    def render_time(self, time, firstrun):
        imgDigi = self.fontDigi.render(time, True, self.meter_section[TIMECOLOR])
        time_rect = pg.Rect(
            self.meter_section[TIME_REMAINING_POS][0], self.meter_section[TIME_REMAINING_POS][1], imgDigi.get_width(), self.fontDigi.get_height()
        )

        if firstrun:  # backup clean area on first run
            self.imgTimeBackup = None
            self.imgTimeBackup = self.screen.subsurface(time_rect).copy()
        self.screen.blit(self.imgTimeBackup, time_rect)
        self.screen.blit(imgDigi, time_rect)
        # update time rectangle
        self.base.update_rectangle(time_rect)

    def render_text(self, firstrun):
        """render text objects"""

        formatIcon = "/volumio/http/www3/app/assets-common/format-icons/" + self.playinfo_trackT + ".svg"

        def set_color(img, color):
            for x in range(img.get_width()):
                for y in range(img.get_height()):
                    color.a = img.get_at((x, y)).a  # Preserve the alpha value.
                    img.set_at((x, y), color)  # Set the color of the pixel.

        def render_txt(rendertxt, fontstyle):
            if fontstyle == FONT_STYLE_L:
                ret = self.fontL.render(rendertxt, True, self.fontcolor)
            elif fontstyle == FONT_STYLE_R:
                ret = self.fontR.render(rendertxt, True, self.fontcolor)
            else:
                ret = self.fontB.render(rendertxt, True, self.fontcolor)
            return ret

        def update_txt(imgtxt, rect):
            if self.meter_section[PLAY_CENTER] == True:  # center title position
                self.screen.blit(imgtxt, (rect.centerx - int(imgtxt.get_width() / 2), rect.y))
            else:
                self.screen.blit(imgtxt, rect)
            self.base.update_rectangle(rect)

        # title, artist, album
        title_str = self.playinfo_title if self.playinfo_tracknumber else self.playinfo_pos + self.playinfo_title
        imgTitle_long = render_txt(title_str, self.meter_section[PLAY_TITLE_STYLE])
        imgArtist_long = render_txt(self.playinfo_artist, self.meter_section[PLAY_ARTIST_STYLE])
        album_str = self.playinfo_album + " (" + self.playinfo_year + ")" if self.playinfo_year else self.playinfo_album
        imgAlbum_long = render_txt(album_str, self.meter_section[PLAY_ALBUM_STYLE])

        # duration + bitrate + samplerate + bitdepth
        text_values = [self.playinfo_duration, self.playinfo_bitrate, self.playinfo_sample, self.playinfo_depth]
        text = ", ".join(filter(None, text_values)).strip()
        maxText = "==88:88/888, 88888 Kbps, 88.8 kHz, 88 bit=="
        if self.meter_section[PLAY_SAMPLE_STYLE] == FONT_STYLE_R:
            img_samplerate = self.fontR.render(text, True, self.meter_section[PLAY_TYPE_COLOR])
            max_text_size = self.fontR.size(maxText)
        elif self.meter_section[PLAY_SAMPLE_STYLE] == FONT_STYLE_B:
            img_samplerate = self.fontB.render(text, True, self.meter_section[PLAY_TYPE_COLOR])
            max_text_size = self.fontB.size(maxText)
        else:
            img_samplerate = self.fontL.render(text, True, self.meter_section[PLAY_TYPE_COLOR])
            max_text_size = self.fontL.size(maxText)

        if self.titleMem != self.playinfo_title:  # only if title changed
            # trackType
            if self.meter_section[PLAY_TYPE_POS] and self.meter_section[PLAY_TYPE_DIM]:
                type_rect = pg.Rect(self.meter_section[PLAY_TYPE_POS], self.meter_section[PLAY_TYPE_DIM])
                if firstrun:  # backup clean area on first run
                    self.imgFormatBackup = None
                    self.imgFormatBackup = self.screen.subsurface(type_rect).copy()
                self.screen.blit(self.imgFormatBackup, type_rect)

                if os.path.exists(formatIcon):
                    try:
                        new_bites = cairosvg.svg2png(url=formatIcon)
                        imgType = Image.open(io.BytesIO(new_bites))

                        # scale
                        imgType.thumbnail((type_rect.width, type_rect.height), Image.ANTIALIAS)
                        # create pygame image surface
                        format_img = pg.image.fromstring(imgType.tobytes(), imgType.size, imgType.mode)
                        set_color(
                            format_img,
                            pg.Color(
                                self.meter_section[PLAY_TYPE_COLOR][0], self.meter_section[PLAY_TYPE_COLOR][1], self.meter_section[PLAY_TYPE_COLOR][2]
                            ),
                        )

                        # center type icon in surface
                        if imgType.height >= imgType.width:
                            PlayTypePos = self.meter_section[PLAY_TYPE_POS]
                        else:
                            PlayTypePos = (
                                self.meter_section[PLAY_TYPE_POS][0],
                                int(self.meter_section[PLAY_TYPE_POS][1] + self.meter_section[PLAY_TYPE_DIM][0] / 2 - imgType.height / 2),
                            )
                        self.screen.blit(format_img, PlayTypePos)

                    # if cairosvg not properly installed use text instead
                    except:
                        if self.meter_section[PLAY_SAMPLE_POS]:
                            if self.meter_section[PLAY_CENTER] == True:
                                typePos_Y = self.meter_section[PLAY_TYPE_POS][1]
                                typeStr = self.playinfo_trackT
                            else:
                                typePos_Y = self.meter_section[PLAY_SAMPLE_POS][1]
                                typeStr = self.playinfo_trackT[:4]

                            if self.meter_section[PLAY_SAMPLE_STYLE] == FONT_STYLE_R:
                                imgTrackT = self.fontR.render(typeStr, True, self.meter_section[PLAY_TYPE_COLOR])
                            elif self.meter_section[PLAY_SAMPLE_STYLE] == FONT_STYLE_B:
                                imgTrackT = self.fontB.render(typeStr, True, self.meter_section[PLAY_TYPE_COLOR])
                            else:
                                imgTrackT = self.fontL.render(typeStr, True, self.meter_section[PLAY_TYPE_COLOR])

                            type_rect = pg.Rect((self.meter_section[PLAY_TYPE_POS][0], typePos_Y), imgTrackT.get_size())
                            self.screen.blit(imgTrackT, type_rect)

                else:
                    # clear area, webradio has no type
                    self.screen.blit(self.imgFormatBackup, type_rect)
                # update tracktype rectangle
                self.base.update_rectangle(type_rect)

            # stop all ticker if title info changed
            self.stop_text_animator()

            # title info
            if self.meter_section[PLAY_TITLE_POS] and self.meter_section[PLAY_MAX]:
                title_rect = pg.Rect(self.meter_section[PLAY_TITLE_POS], (self.meter_section[PLAY_MAX], imgTitle_long.get_height()))
                if firstrun:  # backup clean area on first run
                    self.imgTitleBackup = None
                    self.imgTitleBackup = self.screen.subsurface(title_rect).copy()
                self.screen.blit(self.imgTitleBackup, title_rect)

                if imgTitle_long.get_width() - 5 <= title_rect.width or self.meter_section[PLAY_ANIMATION] == False:
                    update_txt(imgTitle_long, title_rect)
                else:  # start ticker daemon title
                    self.text_animator_title = None
                    self.text_animator_title = self.start_text_animator(self.base, self.imgTitleBackup, imgTitle_long, title_rect)

            # artist info
            if self.meter_section[PLAY_ARTIST_POS] and self.meter_section[PLAY_MAX]:
                artist_rect = pg.Rect(self.meter_section[PLAY_ARTIST_POS], (self.meter_section[PLAY_MAX], imgArtist_long.get_height()))
                if firstrun:  # backup clean area on first run
                    self.imgArtistBackup = None
                    self.imgArtistBackup = self.screen.subsurface(artist_rect).copy()
                self.screen.blit(self.imgArtistBackup, artist_rect)
                # pg.draw.rect(self.screen, (200,200,200), artist_rect)

                if imgArtist_long.get_width() - 5 <= artist_rect.width or self.meter_section[PLAY_ANIMATION] == False:
                    update_txt(imgArtist_long, artist_rect)
                else:  # start ticker daemon artist
                    self.text_animator_artist = None
                    self.text_animator_artist = self.start_text_animator(self.base, self.imgArtistBackup, imgArtist_long, artist_rect)

            # album info
            if self.meter_section[PLAY_ALBUM_POS] and self.meter_section[PLAY_MAX]:
                album_rect = pg.Rect(self.meter_section[PLAY_ALBUM_POS], (self.meter_section[PLAY_MAX], imgAlbum_long.get_height()))
                if firstrun:  # backup clean area on first run
                    self.imgAlbumBackup = None
                    self.imgAlbumBackup = self.screen.subsurface(album_rect).copy()
                self.screen.blit(self.imgAlbumBackup, album_rect)
                # pg.draw.rect(self.screen, (200,200,200), album_rect)

                if imgAlbum_long.get_width() - 5 <= album_rect.width or self.meter_section[PLAY_ANIMATION] == False:
                    update_txt(imgAlbum_long, album_rect)
                else:  # start ticker daemon album
                    self.text_animator_album = None
                    self.text_animator_album = self.start_text_animator(self.base, self.imgAlbumBackup, imgAlbum_long, album_rect)

        # frame rate info
        if self.meter_section[PLAY_SAMPLE_POS]:
            if self.meter_section[PLAY_SAMPLE_RIGHT] == True:
                sample_pos_x = self.meter_section[PLAY_SAMPLE_POS][0] - img_samplerate.get_width()
                sample_max_pos_x = self.meter_section[PLAY_SAMPLE_POS][0] - max_text_size[0]
                sample_rect = pg.Rect((sample_pos_x, self.meter_section[PLAY_SAMPLE_POS][1]), img_samplerate.get_size())
                sample_max_rect = pg.Rect((sample_max_pos_x, self.meter_section[PLAY_SAMPLE_POS][1]), max_text_size)
            else:
                sample_pos_bk = self.meter_section[PLAY_SAMPLE_POS][0]
                sample_pos_x = self.meter_section[PLAY_SAMPLE_POS][0]
                if self.meter_section[PLAY_CENTER] == True:
                    sample_pos_bk += int((self.meter_section[PLAY_MAX] - max_text_size[0]) / 2)
                    sample_pos_x += int((self.meter_section[PLAY_MAX] - img_samplerate.get_width()) / 2)
                sample_rect = pg.Rect((sample_pos_bk, self.meter_section[PLAY_SAMPLE_POS][1]), max_text_size)
                sample_max_rect = sample_rect

            if firstrun:  # backup clean area on first run
                self.empty_samplerate_area = None
                self.empty_samplerate_area = self.screen.subsurface(sample_max_rect).copy()
            self.screen.blit(self.empty_samplerate_area, sample_max_rect)
            self.screen.blit(img_samplerate, (sample_pos_x, sample_rect.y))
            self.base.update_rectangle(sample_rect)

    # text animator functions
    # ----------------------------------
    def start_text_animator(self, base, imgBackup, imgTxt, imgRect):
        """start daemon for text animation"""

        a = TextAnimator(self.util, base, imgBackup, imgTxt, imgRect)
        # a.setDaemon(True)
        a.start()
        return a

    def stop_text_animator(self):
        """stop daemons for text animation"""

        if hasattr(self, "text_animator_title") and self.text_animator_title is not None:
            self.text_animator_title.stop_thread()
            del self.text_animator_title
        if hasattr(self, "text_animator_artist") and self.text_animator_artist is not None:
            self.text_animator_artist.stop_thread()
            del self.text_animator_artist
        if hasattr(self, "text_animator_album") and self.text_animator_album is not None:
            self.text_animator_album.stop_thread()
            del self.text_animator_album
        self.trim_memory()
        time.sleep(self.base.ui_refresh_period * 1.2)

    # cleanup memory on exit
    def trim_memory(self) -> int:
        libc = ctypes.CDLL("libc.so.6")
        return libc.malloc_trim(0)


# ===================================================================================================================
class TextAnimator(Thread):
    """Provides show ticker in a separate thread"""

    def __init__(self, util, base, imgBackup, imgTxt, imgRect):
        """Initializer

        :param util: utility class
        :param ui_refresh_period
        :param imgBackup: backup surface for clean
        :param imTxt: txt surface
        :param imgRect: rectangle for update
        """
        Thread.__init__(self)
        self.base = base
        self.screen = util.PYGAME_SCREEN
        self.backup = imgBackup
        self.txt = imgTxt
        self.rct = imgRect
        self.run_flag = True

    def run(self):
        """Thread method. draw ticker"""

        x = 0
        while self.run_flag:
            self.screen.blit(self.backup, self.rct)
            # pg.draw.rect(self.screen, (200,200,200), self.rct)
            self.screen.blit(self.txt, (self.rct.x, self.rct.y), ((x, 0), self.rct.size))
            if self.rct.width + x >= self.txt.get_width():
                xd = -1  # backward
            elif x <= 0:
                xd = 1  # forward
            x += xd

            self.base.update_rectangle(self.rct)
            time.sleep(self.base.ui_refresh_period)

        self.screen.blit(self.backup, self.rct)
        self.base.update_rectangle(self.rct)

        # cleanup memory
        del self.base
        del self.screen
        del self.backup
        del self.txt
        del self.rct
        self.trim_memory()

    def stop_thread(self):
        """Stop thread"""

        self.run_flag = False
        time.sleep(self.base.ui_refresh_period * 1.2)

    # cleanup memory on exit
    def trim_memory(self) -> int:
        libc = ctypes.CDLL("libc.so.6")
        return libc.malloc_trim(0)


# RepeatTimer for remaining time
class RepeatTimer(Timer):
    def run(self):
        while not self.finished.wait(self.interval):
            self.function(*self.args, **self.kwargs)
