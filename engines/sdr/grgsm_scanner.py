#!/usr/bin/python3
# -*- coding: utf-8 -*-
# @file
# @author (C) 2015 by Piotr Krysik <ptrkrysik@gmail.com>
# @author (C) 2015 by Roman Khassraf <rkhassraf@gmail.com>
# @section LICENSE
#
# Gr-gsm is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3, or (at your option)
# any later version.
#
# Gr-gsm is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with gr-gsm; see the file COPYING.  If not, write to
# the Free Software Foundation, Inc., 51 Franklin Street,
# Boston, MA 02110-1301, USA.
#
#
from core.mLog import *

from gnuradio import blocks
from gnuradio import network
from gnuradio import gr
from gnuradio import eng_notation
from gnuradio.eng_option import eng_option
from gnuradio.filter import firdes
from gnuradio.filter import pfb
from math import pi
from optparse import OptionParser

import math
from gnuradio import gsm
import numpy
import os
import osmosdr
import pmt
import time
import sys
import gnuradio.gsm.arfcn as arfcn
import gc


class multichannel_receiver(gr.hier_block2):
    def __init__(self, arfcns=[], center_freq=935e6, osr=4, tseq=1, wide_samp_rate=2e6):
        gr.hier_block2.__init__(
            self, "Multi Arfcns GSM Receiver",
            gr.io_signature(1, 1, gr.sizeof_gr_complex * 1),
            gr.io_signaturev(len(arfcns), len(arfcns), list(map(lambda x: gr.sizeof_gr_complex * 1, arfcns))),
        )
        self.message_port_register_hier_out("out_c0")
        self.message_port_register_hier_out("out_cx")

        ##################################################
        # Parameters
        ##################################################
        self.arfcns = arfcns
        self.center_freq = center_freq
        self.osr = osr
        self.tseq = tseq
        self.wide_samp_rate = wide_samp_rate
        ##################################################
        # Variables
        ##################################################
        self.samp_rate = samp_rate = 1e6
        self.fcs = fcs = list(map(lambda x: arfcn.arfcn2downlink(x), arfcns))

        ##################################################
        # Blocks
        ##################################################
        self.gsm_receiver = gsm.receiver(osr, arfcns, [tseq], False)
        self.gsm_clock_offset_control = gsm.clock_offset_control(fcs[0], samp_rate, osr)
        self.pfb_arb_resamplers_xxx = []
        self.gsm_inputs = []
        self.blocks_rotators_cc = []

        for i in range(len(self.fcs)):
            resampler = pfb.arb_resampler_ccf(
                samp_rate / wide_samp_rate,
                taps=None,
                flt_size=32)
            resampler.declare_sample_delay(0)
            self.pfb_arb_resamplers_xxx.append(resampler)

            gsm_input = gsm.gsm_input(
                ppm=0,
                osr=osr,
                fc=fcs[i],
                samp_rate_in=samp_rate,
            )
            self.gsm_inputs.append(gsm_input)

            blocks_rotator_cc = blocks.rotator_cc(-2 * pi * (fcs[i] - center_freq) / wide_samp_rate)
            self.blocks_rotators_cc.append(blocks_rotator_cc)

            ##################################################
            # Connections
            ##################################################
            self.msg_connect((self.gsm_clock_offset_control, 'ctrl'), (gsm_input, 'ctrl_in'))
            self.connect((blocks_rotator_cc, 0), (resampler, 0))
            self.connect((gsm_input, 0), (self.gsm_receiver, i))
            self.connect((gsm_input, 0), (self, i))
            self.connect((self, 0), (blocks_rotator_cc, 0))
            self.connect((resampler, 0), (gsm_input, 0))

        self.msg_connect((self.gsm_receiver, 'measurements'), (self.gsm_clock_offset_control, 'measurements'))
        self.msg_connect((self.gsm_receiver, 'C0'), (self, 'out_c0'))
        self.msg_connect((self.gsm_receiver, 'CX'), (self, 'out_cx'))


class sdcch8_decoder_hopping(gr.top_block):
    def __init__(self, arfcns_list=[], ccch_index=2, hsn=5, maio=0, osr=4, ts=1, tseq=0, reclen=5, ppm=0, args=""):
        gr.top_block.__init__(self, "Multy arfncs sdcch8 decoder")

        ##################################################
        # Parameters
        ##################################################
        self.arfcns_list = arfcns_list
        self.ccch_index = ccch_index
        self.hsn = hsn
        self.maio = maio
        self.osr = osr
        self.ts = ts
        self.tseq = tseq

        ##################################################
        # Variables
        ##################################################
        self.arfcns = arfcns = list(arfcns_list)
        self.fcs = fcs = list(map(arfcn.arfcn2downlink, arfcns))
        self.wide_samp_rate = wide_samp_rate = max(1e6, int(math.ceil((max(fcs) - min(fcs)) * 1.1 / 1e6)) * 1e6)
        self.center_freq = center_freq = ((max(fcs) + min(fcs)) / 2)
        snippets_main_after_init(self)
        ##################################################
        # Blocks
        ##################################################
        self.osmosdr_source_0 = osmosdr.source(args="numchan=" + str(1) + " " +
                                                    str(gsm.device.get_default_args(args)))

        self.osmosdr_source_0.set_sample_rate(wide_samp_rate)
        self.osmosdr_source_0.set_center_freq(center_freq, 0)
        self.osmosdr_source_0.set_freq_corr(ppm, 0)

        self.osmosdr_source_0.set_dc_offset_mode(2, 0)
        self.osmosdr_source_0.set_iq_balance_mode(0, 0)
        self.osmosdr_source_0.set_gain_mode(True, 0)
        self.osmosdr_source_0.set_bandwidth(0, 0)
        self.osmosdr_source_0.set_gain(14, 0)
        self.osmosdr_source_0.set_if_gain(40, 0)
        self.osmosdr_source_0.set_bb_gain(32, 0)
        self.gsm_sdcch8_demapper_0 = gsm.gsm_sdcch8_demapper(
            timeslot_nr=ts,
        )
        self.gsm_multiarfcns_receiver_0 = multichannel_receiver(
            arfcns=[arfcns[ccch_index]] + arfcns[0:ccch_index] + arfcns[(ccch_index + 1):len(arfcns)],
            center_freq=center_freq,
            osr=osr,
            tseq=tseq,
            wide_samp_rate=wide_samp_rate,
        )

        self.gsm_extract_cmc_0 = gsm.extract_cmc()
        self.gsm_cx_channel_hopper_0 = gsm.cx_channel_hopper(arfcns, maio, hsn)
        self.gsm_control_channels_decoder_0 = gsm.control_channels_decoder()
        self.blocks_head_0 = blocks.head(gr.sizeof_gr_complex * 1, int(wide_samp_rate * reclen))

        self.blocks_socket_pdu_0 = network.socket_pdu('UDP_CLIENT', '127.0.0.1', '4729', 10000, False)

        ##################################################
        # Connections
        ##################################################
        self.msg_connect((self.gsm_control_channels_decoder_0, 'msgs'), (self.blocks_socket_pdu_0, 'pdus'))
        self.msg_connect((self.gsm_control_channels_decoder_0, 'msgs'), (self.gsm_extract_cmc_0, 'msgs'))
        self.msg_connect((self.gsm_cx_channel_hopper_0, 'bursts'), (self.gsm_sdcch8_demapper_0, 'bursts'))
        self.msg_connect((self.gsm_multiarfcns_receiver_0, 'out_c0'), (self.gsm_cx_channel_hopper_0, 'CX'))
        self.msg_connect((self.gsm_multiarfcns_receiver_0, 'out_cx'), (self.gsm_cx_channel_hopper_0, 'CX'))
        self.msg_connect((self.gsm_sdcch8_demapper_0, 'bursts'), (self.gsm_control_channels_decoder_0, 'bursts'))
        self.connect((self.blocks_head_0, 0), (self.gsm_multiarfcns_receiver_0, 0))
        self.connect((self.osmosdr_source_0, 0), (self.blocks_head_0, 0))

    def get_arfcns_list(self):
        return self.arfcns_list

    def set_arfcns_list(self, arfcns_list):
        self.arfcns_list = arfcns_list

    def get_ccch_index(self):
        return self.ccch_index

    def set_ccch_index(self, ccch_index):
        self.ccch_index = ccch_index

    def get_hsn(self):
        return self.hsn

    def set_hsn(self, hsn):
        self.hsn = hsn

    def get_maio(self):
        return self.maio

    def set_maio(self, maio):
        self.maio = maio

    def get_osr(self):
        return self.osr

    def set_osr(self, osr):
        self.osr = osr
        self.gsm_multiarfcns_receiver_0.set_osr(self.osr)

    def get_ts(self):
        return self.ts

    def set_ts(self, ts):
        self.ts = ts
        self.gsm_sdcch8_demapper_0.set_timeslot_nr(self.ts)

    def get_tseq(self):
        return self.tseq

    def set_tseq(self, tseq):
        self.tseq = tseq
        self.gsm_multiarfcns_receiver_0.set_tseq(self.tseq)

    def get_arfcns(self):
        return self.arfcns

    def set_arfcns(self, arfcns):
        self.arfcns = arfcns
        self.set_fcs(list(map(arfcn.arfcn2downlink, self.arfcns)))

    def get_fcs(self):
        return self.fcs

    def set_fcs(self, fcs):
        self.fcs = fcs
        self.set_center_freq(((max(self.fcs) + min(self.fcs)) / 2))
        self.set_wide_samp_rate(max(1e6, int(math.ceil((max(self.fcs) - min(self.fcs)) * 1.1 / 1e6)) * 1e6))

    def get_wide_samp_rate(self):
        return self.wide_samp_rate

    def set_wide_samp_rate(self, wide_samp_rate):
        self.wide_samp_rate = wide_samp_rate
        self.blocks_head_0.set_length(int(self.wide_samp_rate * 30))
        self.gsm_multiarfcns_receiver_0.set_wide_samp_rate(self.wide_samp_rate)
        self.osmosdr_source_0.set_sample_rate(self.wide_samp_rate)

    def get_center_freq(self):
        return self.center_freq

    def set_center_freq(self, center_freq):
        self.center_freq = center_freq
        self.gsm_multiarfcns_receiver_0.set_center_freq(self.center_freq)
        self.osmosdr_source_0.set_center_freq(self.center_freq, 0)


def snipfcn_check_bandwidth(self):
    if (self.wide_samp_rate > 20e6):  # for hackrf
        print("Very wide bandwidth for this arfcns: " + str(self.wide_samp_rate / 1e6) + " MHz")
        self.stop()
    else:
        print("Wide bandwidth: " + str(self.wide_samp_rate / 1e6) + " MHz")


def snippets_main_after_init(tb):
    snipfcn_check_bandwidth(tb)


# from wideband_receiver import *

class receiver_with_decoder(gr.hier_block2):
    def __init__(self, OSR=4, chan_num=0, fc=939.4e6, ppm=0, samp_rate=0.2e6):
        gr.hier_block2.__init__(
            self, "Receiver With Decoder",
            gr.io_signature(1, 1, gr.sizeof_gr_complex * 1),
            gr.io_signature(0, 0, 0),
        )
        self.message_port_register_hier_out("bursts")
        self.message_port_register_hier_out("msgs")

        ##################################################
        # Parameters
        ##################################################
        self.OSR = OSR
        self.chan_num = chan_num
        self.fc = fc
        self.ppm = ppm
        self.samp_rate = samp_rate

        ##################################################
        # Variables
        ##################################################
        self.samp_rate_out = samp_rate_out = 1625000.0 / 6.0 * OSR

        ##################################################
        # Blocks
        ##################################################
        self.gsm_receiver_0 = gsm.receiver(OSR, ([chan_num]), ([]))
        self.gsm_input_0 = gsm.gsm_input(
            ppm=ppm,
            osr=OSR,
            fc=fc,
            samp_rate_in=samp_rate,
        )
        self.gsm_control_channels_decoder_0 = gsm.control_channels_decoder()
        self.gsm_clock_offset_control_0 = gsm.clock_offset_control(fc, samp_rate, osr=4)
        self.gsm_bcch_ccch_demapper_0 = gsm.gsm_bcch_ccch_demapper(0)

        ##################################################
        # Connections
        ##################################################
        self.msg_connect(self.gsm_bcch_ccch_demapper_0, 'bursts', self, 'bursts')
        self.msg_connect(self.gsm_bcch_ccch_demapper_0, 'bursts', self.gsm_control_channels_decoder_0, 'bursts')
        self.msg_connect(self.gsm_clock_offset_control_0, 'ctrl', self.gsm_input_0, 'ctrl_in')
        self.msg_connect(self.gsm_control_channels_decoder_0, 'msgs', self, 'msgs')
        self.msg_connect(self.gsm_receiver_0, 'C0', self.gsm_bcch_ccch_demapper_0, 'bursts')
        self.msg_connect(self.gsm_receiver_0, 'measurements', self.gsm_clock_offset_control_0, 'measurements')
        self.connect((self.gsm_input_0, 0), (self.gsm_receiver_0, 0))
        self.connect((self, 0), (self.gsm_input_0, 0))

    def get_OSR(self):
        return self.OSR

    def set_OSR(self, OSR):
        self.OSR = OSR
        self.set_samp_rate_out(1625000.0 / 6.0 * self.OSR)
        self.gsm_input_0.set_osr(self.OSR)

    def get_chan_num(self):
        return self.chan_num

    def set_chan_num(self, chan_num):
        self.chan_num = chan_num

    def get_fc(self):
        return self.fc

    def set_fc(self, fc):
        self.fc = fc
        self.gsm_input_0.set_fc(self.fc)

    def get_ppm(self):
        return self.ppm

    def set_ppm(self, ppm):
        self.ppm = ppm
        self.gsm_input_0.set_ppm(self.ppm)

    def get_samp_rate(self):
        return self.samp_rate

    def set_samp_rate(self, samp_rate):
        self.samp_rate = samp_rate
        self.gsm_input_0.set_samp_rate_in(self.samp_rate)

    def get_samp_rate_out(self):
        return self.samp_rate_out

    def set_samp_rate_out(self, samp_rate_out):
        self.samp_rate_out = samp_rate_out


class wideband_receiver(gr.hier_block2):
    def __init__(self, OSR=4, fc=939.4e6, samp_rate=0.4e6):
        gr.hier_block2.__init__(
            self, "Wideband receiver",
            gr.io_signature(1, 1, gr.sizeof_gr_complex * 1),
            gr.io_signature(0, 0, 0),
        )
        self.message_port_register_hier_out("bursts")
        self.message_port_register_hier_out("msgs")
        self.__init(OSR, fc, samp_rate)

    def __init(self, OSR=4, fc=939.4e6, samp_rate=0.4e6):
        ##################################################
        # Parameters
        ##################################################
        self.OSR = OSR
        self.fc = fc
        self.samp_rate = samp_rate
        self.channels_num = int(samp_rate / 0.2e6)
        self.OSR_PFB = 2

        ##################################################
        # Blocks
        ##################################################
        self.pfb_channelizer_ccf_0 = pfb.channelizer_ccf(
            self.channels_num,
            (),
            self.OSR_PFB,
            100)
        self.pfb_channelizer_ccf_0.set_channel_map(([]))
        self.create_receivers()

        ##################################################
        # Connections
        ##################################################
        self.connect((self, 0), (self.pfb_channelizer_ccf_0, 0))
        for chan in range(0, self.channels_num):
            self.connect((self.pfb_channelizer_ccf_0, chan), (self.receivers_with_decoders[chan], 0))
            self.msg_connect(self.receivers_with_decoders[chan], 'bursts', self, 'bursts')
            self.msg_connect(self.receivers_with_decoders[chan], 'msgs', self, 'msgs')

    def create_receivers(self):
        self.receivers_with_decoders = {}
        for chan in range(0, self.channels_num):
            self.receivers_with_decoders[chan] = receiver_with_decoder(fc=self.fc, OSR=self.OSR, chan_num=chan,
                                                                       samp_rate=self.OSR_PFB * 0.2e6)

    def get_OSR(self):
        return self.OSR

    def set_OSR(self, OSR):
        self.OSR = OSR
        self.create_receivers()

    def get_fc(self):
        return self.fc

    def set_fc(self, fc):
        self.fc = fc
        self.create_receivers()

    def get_samp_rate(self):
        return self.samp_rate


class wideband_scanner(gr.top_block):
    def __init__(self, rec_len=3, sample_rate=2e6, carrier_frequency=939e6, gain=40, ppm=0, args=""):
        gr.top_block.__init__(self, "Wideband Scanner")

        self.rec_len = rec_len
        self.sample_rate = sample_rate
        self.carrier_frequency = carrier_frequency
        self.ppm = ppm

        # if no file name is given process data from rtl_sdr source
        print("Args=", args)
        self.rtlsdr_source = osmosdr.source(args="numchan=" + str(1) + " " +
                                                 str(gsm.device.get_default_args(args)))
        # self.rtlsdr_source.set_min_output_buffer(int(sample_rate*rec_len)) #this line causes segfaults on HackRF
        self.rtlsdr_source.set_sample_rate(sample_rate)

        # capture half of GSM channel lower than channel center (-0.1MHz)
        # this is needed when even number of channels is captured in order to process full captured bandwidth

        self.rtlsdr_source.set_center_freq(carrier_frequency - 0.1e6, 0)

        # correction of central frequency
        # if the receiver has large frequency offset
        # the value of this variable should be set close to that offset in ppm
        self.rtlsdr_source.set_freq_corr(ppm, 0)

        self.rtlsdr_source.set_dc_offset_mode(2, 0)
        self.rtlsdr_source.set_iq_balance_mode(0, 0)
        self.rtlsdr_source.set_gain_mode(True, 0)
        self.rtlsdr_source.set_bandwidth(sample_rate, 0)
        self.rtlsdr_source.set_gain(gain, 0)
        self.rtlsdr_source.set_if_gain(40, 0)
        self.rtlsdr_source.set_bb_gain(32, 0)
        self.head = blocks.head(gr.sizeof_gr_complex * 1, int(rec_len * sample_rate))

        # shift again by -0.1MHz in order to align channel center in 0Hz
        self.blocks_rotator_cc = blocks.rotator_cc(-2 * pi * 0.1e6 / sample_rate)

        self.wideband_receiver = wideband_receiver(OSR=4, fc=carrier_frequency, samp_rate=sample_rate)
        self.extract_immediate_assignment = gsm.extract_immediate_assignment(False, True, True)
        self.gsm_extract_system_info = gsm.extract_system_info()

        self.connect((self.rtlsdr_source, 0), (self.head, 0))
        self.connect((self.head, 0), (self.blocks_rotator_cc, 0))
        self.connect((self.blocks_rotator_cc, 0), (self.wideband_receiver, 0))
        self.msg_connect(self.wideband_receiver, 'msgs', self.gsm_extract_system_info, 'msgs')
        self.msg_connect(self.wideband_receiver, 'msgs', self.extract_immediate_assignment, 'msgs')

    def set_carrier_frequency(self, carrier_frequency):
        self.carrier_frequency = carrier_frequency
        self.rtlsdr_source.set_center_freq(carrier_frequency - 0.1e6, 0)


class assignment_info(object):
    def __init__(self, arfcn, channel, timeslot, tseq, maio, hsn, a5_vers=[]):
        self.arfcn = arfcn
        self.assignment_channel = channel
        self.timeslot = timeslot
        self.tseq = tseq
        self.maio = maio
        self.hsn = hsn
        self.a5_vers = a5_vers

    def __str__(self):
        return str(self.assignment_channel) + ", Timeslot: " + str(self.timeslot) + ", Training Sequence: " + str(
            self.tseq) + ", MAIO: " + str(self.maio) + ", HSN: " + str(self.hsn) + ", A5/1 Version: " + ", ".join(
            map(str, list(set(self.a5_vers))))


class channel_info(object):
    def __init__(self, arfcn, freq, cid, lac, mcc, mnc, ccch_conf, power, neighbours, cell_arfcns, assignments):
        self.arfcn = arfcn
        self.freq = freq
        self.cid = cid
        self.lac = lac
        self.mcc = mcc
        self.mnc = mnc
        self.ccch_conf = ccch_conf
        self.power = power
        self.neighbours = neighbours
        self.cell_arfcns = cell_arfcns
        self.assignments = assignments

    def __lt__(self, other):
        return self.arfcn < other.arfcn

    def get_verbose_info(self):
        v = "  |---- Configuration: %s\n" % self.get_ccch_conf()
        v += "  |---- Cell ARFCNs: " + ", ".join(map(str, self.cell_arfcns)) + "\n"
        if len(self.assignments) > 0:
            v += "  |---- DCCHs:\n"
        for i in range(0, len(self.assignments)):
            v += "  |-------- " + "#" + str(i + 1) + " " + str(self.assignments[i]) + "\n"

        v += "  |---- Neighbour Cells: " + ", ".join(map(str, self.neighbours)) + "\n"

        return v

    def get_ccch_conf(self):
        if self.ccch_conf == 0:
            return "1 CCCH, not combined"
        elif self.ccch_conf == 1:
            return "1 CCCH, combined"
        elif self.ccch_conf == 2:
            return "2 CCCH, not combined"
        elif self.ccch_conf == 4:
            return "3 CCCH, not combined"
        elif self.ccch_conf == 6:
            return "4 CCCH, not combined"
        else:
            return "Unknown"

    def getKey(self):
        return self.arfcn


    @Cellslogger
    def attr2dic(self):
        cell = {}
        cid2 = str(self.cid) + '_' + str(self.arfcn)
        cell[cid2] = {'PLMN' : str(self.mcc)+str(self.mnc),
                      'arfcn' : int(self.arfcn),
                      'type' : '2G',
                      'cid' : str(self.cid)}
        return cell


    def __cmp__(self, other):
        if hasattr(other, 'getKey'):
            return self.getKey().__cmp__(other.getKey())

    def __repr__(self):
        return "%s(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)" % (
            self.__class__, self.arfcn, self.freq, self.cid, self.lac,
            self.mcc, self.mnc, self.ccch_conf, self.power,
            self.neighbours, self.cell_arfcns)

    def __str__(self):
        return "ARFCN: %4u, Freq: %6.1fM, CID: %5u, LAC: %5u, MCC: %3u, MNC: %3u, Pwr: %3i" % (
            self.arfcn, self.freq / 1e6, self.cid, self.lac, self.mcc, self.mnc, self.power)


def do_scan(samp_rate, band, speed, ppm, gain, args, prn=None, debug=False):
    signallist = []
    server = network.socket_pdu('UDP_SERVER', '127.0.0.1', '4729', 10000, False)
    channels_num = int(samp_rate / 0.2e6)
    for arfcn_range in gsm.arfcn.get_arfcn_ranges(band):
        first_arfcn = arfcn_range[0]
        last_arfcn = arfcn_range[1]
        print("Try scan CCCH on " + str(first_arfcn) + "-" + str(last_arfcn) + " arfcn`s:")
        last_center_arfcn = last_arfcn - int((channels_num / 2) - 1)

        start_freq = gsm.arfcn.arfcn2downlink(first_arfcn + int(channels_num / 2) - 1)
        current_freq = start_freq
        last_freq = gsm.arfcn.arfcn2downlink(last_center_arfcn)
        stop_freq = last_freq + 0.2e6 * channels_num

        while current_freq < stop_freq:
            print("Scanning: {percent:.2f}% done..".format(
                percent=(current_freq - start_freq) / (stop_freq - start_freq) * 100))
            if not debug:
                # silence rtl_sdr output:
                # open 2 fds
                null_fds = [os.open(os.devnull, os.O_RDWR) for x in range(2)]
                # save the current file descriptors to a tuple
                save = os.dup(1), os.dup(2)
                # put /dev/null fds on 1 and 2
                os.dup2(null_fds[0], 1)
                os.dup2(null_fds[1], 2)
            # instantiate scanner and processor
            scanner = wideband_scanner(rec_len=30 - speed,
                                       sample_rate=samp_rate,
                                       carrier_frequency=current_freq,
                                       ppm=ppm, gain=gain, args=args)
            # start recording
            scanner.start()
            scanner.wait()
            scanner.stop()
            if not debug:
                # restore file descriptors so we can print the results
                os.dup2(save[0], 1)
                os.dup2(save[1], 2)
                # close the temporary fds
                os.close(null_fds[0])
                os.close(null_fds[1])

            freq_offsets = numpy.fft.ifftshift(
                numpy.array(range(int(-numpy.floor(channels_num / 2)), int(numpy.floor((channels_num + 1) / 2)))) * 2e5)
            detected_c0_channels = scanner.gsm_extract_system_info.get_chans()

            found_list = []

            if detected_c0_channels:
                chans = numpy.array(scanner.gsm_extract_system_info.get_chans())
                found_freqs = current_freq + freq_offsets[(chans)]

                cell_ids = numpy.array(scanner.gsm_extract_system_info.get_cell_id())
                lacs = numpy.array(scanner.gsm_extract_system_info.get_lac())
                mccs = numpy.array(scanner.gsm_extract_system_info.get_mcc())
                mncs = numpy.array(scanner.gsm_extract_system_info.get_mnc())
                ccch_confs = numpy.array(scanner.gsm_extract_system_info.get_ccch_conf())
                powers = numpy.array(scanner.gsm_extract_system_info.get_pwrs())
                assignment_arfcns = numpy.array(scanner.extract_immediate_assignment.get_arfcn_ids())
                assignment_tseqs = numpy.array(scanner.extract_immediate_assignment.get_tseqs())
                assignment_maios = numpy.array(scanner.extract_immediate_assignment.get_maios())
                assignment_hsns = numpy.array(scanner.extract_immediate_assignment.get_hsns())
                assignment_timeslots = numpy.array(scanner.extract_immediate_assignment.get_timeslots())
                assignment_channels = numpy.array(scanner.extract_immediate_assignment.get_channel_types())
                cell_arfcn_lists = []
                neighbour_lists = []
                for i in range(0, len(chans)):
                    cell_arfcn_lists.append(scanner.gsm_extract_system_info.get_cell_arfcns(chans[i]))
                    neighbour_lists.append(scanner.gsm_extract_system_info.get_neighbours(chans[i]))
                scanner = None
                gc.collect()
                for i in range(0, len(chans)):
                    cell_arfcn_list = cell_arfcn_lists[i]
                    neighbour_list = neighbour_lists[i]
                    found_arfcn = gsm.arfcn.downlink2arfcn(found_freqs[i])
                    print("\nFound CCCH arfcn: " + str(found_arfcn))
                    found_arfcn_assignments = []

                    for a in range(0, len(assignment_arfcns)):

                        # print("Assigments: " + str(assignment_arfcns[a]) + "<->" + str(chans[i]))
                        if assignment_arfcns[a] == chans[i]:
                            dubl = False
                            for f in found_arfcn_assignments:
                                if f.assignment_channel == assignment_channels[a] and \
                                        f.timeslot == assignment_timeslots[a] and \
                                        f.tseq == assignment_tseqs[a] and \
                                        f.maio == assignment_maios[a] and \
                                        f.hsn == assignment_hsns[a]:
                                    dubl = True
                                    break
                            if not dubl:
                                a5_versions = []
                                if len(cell_arfcn_list) > 0:
                                    fcs = list(map(arfcn.arfcn2downlink, cell_arfcn_list))
                                    wide_samp_rate = max(1e6, int(math.ceil((max(fcs) - min(fcs)) * 1.1 / 1e6)) * 1e6)
                                    if wide_samp_rate > 20e6:
                                        # print("Very wide bandwidth for this hopping SDCCH/8 arfcns: " + str(wide_samp_rate/1e6) + " MHz, skip SDCCH/8 scan...")
                                        a5_versions = [
                                            "?, arfcn`s range too wide: " + str(wide_samp_rate / 1e6) + " MHz"]
                                    else:
                                        try:
                                            # print("Wide bandwidth: " + str(wide_samp_rate/1e6) + " MHz")
                                            # print(", ".join(map(str, cell_arfcn_list)))
                                            # print(found_arfcn)
                                            ccch_index = tuple(cell_arfcn_list).index(found_arfcn)
                                            print("Start SDCCH/8 scanning on " + str(found_arfcn) + " arfcn...")
                                            for t in range(0, 6):
                                                print(str(t + 1) + "`th try..")
                                                if not debug:
                                                    # silence rtl_sdr output:
                                                    # open 2 fds
                                                    null_fds = [os.open(os.devnull, os.O_RDWR) for x in range(2)]
                                                    # save the current file descriptors to a tuple
                                                    save = os.dup(1), os.dup(2)
                                                    # put /dev/null fds on 1 and 2
                                                    os.dup2(null_fds[0], 1)
                                                    os.dup2(null_fds[1], 2)
                                                sdcch8_scanner = sdcch8_decoder_hopping(cell_arfcn_list, ccch_index,
                                                                                        assignment_hsns[a],
                                                                                        assignment_maios[a], 4,
                                                                                        assignment_timeslots[a],
                                                                                        assignment_tseqs[a], 30, ppm,
                                                                                        args)
                                                if not debug:
                                                    os.dup2(save[0], 1)
                                                    os.dup2(save[1], 2)
                                                    # close the temporary fds
                                                    os.close(null_fds[0])
                                                    os.close(null_fds[1])
                                                sdcch8_scanner.start()
                                                sdcch8_scanner.wait()
                                                sdcch8_scanner.stop()
                                                a5_versions = sdcch8_scanner.gsm_extract_cmc_0.get_a5_versions()
                                                if len(a5_versions) == 0:
                                                    a5_versions = ["?, not found CMC"]
                                                else:
                                                    break
                                                # print(", ".join(map(str, a5_versions)))
                                                sdcch8_scanner = None
                                                gc.collect()
                                        except ValueError:
                                            # print("Found arfcn not present in arfcns hopping list, skip SDCCH/8 scan...")
                                            a5_versions = [
                                                "?, this CCCH is not present in hopping list | possible signal imposition"]
                                else:
                                    print(
                                        "!! Immidiate assigment got, but SDCCH/8 Channel Description not capture, skip SDCCH/8 scan...")
                                    a5_versions = ["?, SDCCH/8 channel description not capture"]
                                found_arfcn_assignments.append(assignment_info(found_arfcn, assignment_channels[a],
                                                                               assignment_timeslots[a],
                                                                               assignment_tseqs[a],
                                                                               assignment_maios[a], assignment_hsns[a],
                                                                               a5_versions))
                    if len(found_arfcn_assignments) == 0:
                        print("Dont capture immediate assignments, skip extract SDCCH/8 info and scan...")
                    info = channel_info(found_arfcn, found_freqs[i],
                                        cell_ids[i], lacs[i], mccs[i], mncs[i], ccch_confs[i], powers[i],
                                        neighbour_list, cell_arfcn_list, found_arfcn_assignments)

                    print(info)
                    print(info.get_verbose_info())

                    found_list.append(info)

            scanner = None

            if prn:
                prn(found_list)
            signallist.extend(found_list)

            current_freq += channels_num * 0.2e6
    server = None
    return signallist


def argument_parser():
    parser = OptionParser(option_class=eng_option, usage="%prog: [options]")
    bands_list = ", ".join(gsm.arfcn.get_bands())
    parser.add_option("-b", "--band", dest="band", default="GSM900",
                      help="Specify the GSM band for the frequency.\nAvailable bands are: " + bands_list)
    parser.add_option("-s", "--samp-rate", dest="samp_rate", type="float", default=2e6,
                      help="Set sample rate [default=%default] - allowed values even_number*0.2e6")
    parser.add_option("-p", "--ppm", dest="ppm", type="intx", default=0,
                      help="Set frequency correction in ppm [default=%default]")
    parser.add_option("-g", "--gain", dest="gain", type="eng_float", default=24.0,
                      help="Set gain [default=%default]")
    parser.add_option("", "--args", dest="args", type="string", default="",
                      help="Set device arguments [default=%default]."
                           " Use --list-devices the view the available devices")
    parser.add_option("-l", "--list-devices", action="store_true",
                      help="List available SDR devices, use --args to specify hints")
    parser.add_option("--speed", dest="speed", type="intx", default=15,
                      help="Scan speed [default=%default]. Value range 0-29.")
    parser.add_option("-v", "--verbose", action="store_true",
                      help="If set, verbose information output is printed: ccch configuration, cell ARFCN's, neighbour ARFCN's")
    parser.add_option("-d", "--debug", action="store_true",
                      help="Print additional debug messages")

    """
        Dont forget: sudo sysctl kernel.shmmni=32000
    """
    return parser


def main(options=None):
    if options is None:
        (options, args) = argument_parser().parse_args()

    if options.list_devices:
        gsm.device.print_devices(options.args)
        sys.exit(0)

    if options.band not in gsm.arfcn.get_bands():
        parser.error("Invalid GSM band\n")

    if options.speed < 0 or options.speed > 29:
        parser.error("Invalid scan speed.\n")

    if (options.samp_rate / 0.2e6) % 2 != 0:
        parser.error("Invalid sample rate. Sample rate must be an even numer * 0.2e6")

    # def printfunc(found_list):
    # for info in sorted(found_list):
    #     print(info)
    #     if options.verbose:
    #         print(info.get_verbose_info())
    print("")
    do_scan(options.samp_rate, options.band, options.speed,
            options.ppm, options.gain, options.args, prn=None, debug=options.debug)


if __name__ == '__main__':
    main()
