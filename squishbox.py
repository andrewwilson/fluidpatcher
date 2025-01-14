#!/usr/bin/env python3
"""
Description: an implementation of patcher.py for a Raspberry Pi in a stompbox
"""
import re, sys, os, subprocess
from pathlib import Path
import patcher
from utils import stompboxpi as SB

BUTTON_MIDICHANNEL = 16
BUTTON_MOM_CC = 30, 
BUTTON_TOG_CC = 31, 


button_state = [0] * len(BUTTON_TOG_CC)

def exceptstr(e): return re.sub(' {2,}', ' ', re.sub('\n|\^', ' ', str(e)))
    
def sver2ints(v): return list(map(int, v.split('.')))

def wifi_settings():
    x = re.search("SSID: ([^\n]+)", subprocess.check_output("iw dev wlan0 link".split(), encoding='ascii'))
    ssid = x[1] if x else "Not connected"
    ip = subprocess.check_output(['hostname', '-I'], encoding='ascii').strip()
    sb.lcd_clear()
    sb.lcd_write(ssid, 0)
    sb.lcd_write(ip, 1, rjust=True)
    if not sb.waitfortap(10): return
    while True:
        sb.lcd_write("Connections:", 0)
        opts = [*networks, 'Rescan..']
        j = sb.choose_opt(opts, row=1, scroll=True, timeout=0)
        if j < 0: return
        elif j == len(networks):
            sb.lcd_write("scanning ", 1, rjust=True, now=True)
            sb.progresswheel_start()
            x = subprocess.check_output("sudo iw wlan0 scan".split(), encoding='ascii')
            sb.progresswheel_stop()
            networks[:] = [s for s in re.findall('SSID: ([^\n]*)', x) if s]
        else:
            sb.lcd_write("Password:", 0)
            newpsk = sb.char_input(charset = SB.PRNCHARS)
            if newpsk == '': return
            sb.lcd_clear()
            sb.lcd_write(networks[j], 0)
            sb.lcd_write("adding network ", 1, rjust=True, now=True)
            sb.progresswheel_start()
            subprocess.run(f"""echo '
network={{
  ssid="{net}"
  psk="{psk}"
}}
' | sudo tee -a /etc/wpa_supplicant/wpa_supplicant.conf""", shell=True)
            subprocess.run("sudo systemctl restart dhcpcd".split())
            sb.progresswheel_stop()
            wifi_settings()
            return

def file_transfer():
    sb.lcd_clear()
    sb.lcd_write("File Transfer:", 0)
    b = subprocess.check_output(['sudo', 'blkid'], encoding='ascii')
    usb = re.search('/dev/sd[a-z]\d*', b)
    if not usb:
        sb.lcd_write("USB not found", 1)
        sb.waitfortap(2)
        return
    j = sb.choose_opt(['Copy from USB', 'Copy to USB', 'Sync with USB'], row=1)
    if j < 0: return
    sb.lcd_write(['Copy from USB', 'Copy to USB', 'Sync with USB'][j], row=0)
    sb.lcd_write("copying files ", 1, rjust=True, now=True)
    sb.progresswheel_start()
    try:
        subprocess.run("sudo mkdir -p /mnt/usbdrv", shell=True)
        subprocess.run(f"sudo mount -o owner,fmask=0000,dmask=0000 {usb[0]} /mnt/usbdrv/", shell=True)
        if j == 0:
            subprocess.run("rsync -rtL /mnt/usbdrv/SquishBox/ SquishBox/", shell=True)
        elif j == 1:
            subprocess.run("rsync -rtL SquishBox/ /mnt/usbdrv/SquishBox/", shell=True)
        elif j == 2:
            subprocess.run("rsync -rtLu /mnt/usbdrv/SquishBox/ SquishBox/", shell=True)
            subprocess.run("rsync -rtLu SquishBox/ /mnt/usbdrv/SquishBox/", shell=True)
        subprocess.run("sudo umount /mnt/usbdrv", shell=True)
    except Exception as e:
        sb.progresswheel_stop()
        sb.lcd_write(f"halted - errors: {exceptstr(e)}", 1, scroll=True)
        sb.waitfortap()
    else:
        sb.progresswheel_stop()

def update_device():
    sb.lcd_write("Update Device:", 0)
    sb.lcd_write("checking ", 1, rjust=True, now=True)
    sb.progresswheel_start()
    try:
        fpver = re.search('tag_name": "v([0-9\.]+)', subprocess.check_output(['curl', '-s',
            'https://api.github.com/repos/albedozero/fluidpatcher/releases/latest'], encoding='ascii'))[1]
        fsver = re.search('tag_name": "v([0-9\.]+)', subprocess.check_output(['curl', '-s',
            'https://api.github.com/repos/FluidSynth/fluidsynth/releases/latest'], encoding='ascii'))[1]
    except subprocess.CalledProcessError:
        sb.progresswheel_stop()
        sb.lcd_write("can't connect", 1)
        sb.waitfortap()
        return
    sb.progresswheel_stop()
    fpup, fsup, sysup = 0, 0, 0
    if sver2ints(fpver) > sver2ints(patcher.VERSION):
        fpup = sb.confirm_choice("software", row=1, timeout=0)
    if sver2ints(fsver) > sver2ints(patcher.FLUID_VERSION):
        fsup = sb.confirm_choice("fluidsynth", row=1, timeout=0)
    sysup = sb.confirm_choice("system", row=1, timeout=0)
    if not (fpup or fsup or sysup): return
    sb.lcd_write("please wait", 0)
    sb.lcd_write("updating ", 1, rjust=True, now=True)
    sb.progresswheel_start()
    try:
        if fpup:
            subprocess.run("""
wget -qO - https://github.com/albedozero/fluidpatcher/tarball/master | tar -xzm
fptemp=`ls -dt albedozero-fluidpatcher-* | head -n1`
cd $fptemp
find . -type d -exec mkdir -p ../{} \;
find . -type f ! -name "*.yaml" ! -name "hw_overlay.py" -exec cp -f {} ../{} \;
find . -type f -name "hw_overlay.py" -exec cp -n {} ../{} \;
find . -type f -name "*.yaml" -exec cp -n {} ../{} \;
cd ..
rm -rf $fptemp
""", shell=True)
        if fsup:
            subprocess.run("""
sudo sed -i "/^#deb-src/s|#||" /etc/apt/sources.list
sudo apt-get update
sudo DEBIAN_FRONTEND=noninteractive apt-get build-dep fluidsynth -y --no-install-recommends
wget -qO - https://github.com/FluidSynth/fluidsynth/tarball/master | tar -xzm
fstemp=`ls -dt FluidSynth-fluidsynth-* | head -n1`
mkdir $fstemp/build
cd $fstemp/build
cmake ..
make
sudo make install
sudo ldconfig
cd ../..
rm -rf $fstemp
""", shell=True)
        if sysup:
            subprocess.run("sudo apt-get update".split())
            subprocess.run("sudo apt-get upgrade -y".split())
        sb.progresswheel_stop()
        sb.lcd_write("rebooting", 1, rjust=True, now=True)
        subprocess.run(['sudo', 'reboot'])
    except Exception as e:
        sb.progresswheel_stop()
        sb.lcd_write(f"halted - errors: {exceptstr(e)}", 1, scroll=True)
        sb.waitfortap()

def choose_file(topdir, ext=None, last=""):
    cdir = topdir if last == "" else last.parent
    while True:
        sb.lcd_write(str(cdir.relative_to(topdir.parent)) + "/:", 0, scroll=True)
        x = sorted([p for p in cdir.glob('*') if p.is_dir() or p.suffix == ext or ext == None])
        y = [SB.SUBDIR + p.name + "/" if p.is_dir() else p.name for p in x]
        i = x.index(last) if last in x else 0
        if cdir != topdir:
            x.append(cdir.parent)
            y.append(SB.UPDIR + " up directory")
        j = sb.choose_opt(y, i, row=1, scroll=True, timeout=0)
        if j < 0: return ""
        if x[j].is_dir():
            last = cdir
            cdir = x[j]
        else:
            return x[j]


class SquishBox:

    def __init__(self):
        self.pno = 0
        pxr.set_midimessage_callback(self.listener)
        if not (pxr.currentbank and self.load_bank(pxr.currentbank)):
            while not self.load_bank(): pass
        self.patchmode()

    def listener(self, msg):
        if hasattr(msg, 'val'):
            if hasattr(msg, 'patch'):
                pnew = pxr.parse_patchmsg(msg, self.pno)
                if pnew > -1: self.pno = pnew
            elif hasattr(msg, 'lcdwrite'):
                if hasattr(msg, 'format'):
                    val = format(msg.val, msg.format)
                    self.maindisplay[1] = f"{msg.lcdwrite} {val}"
                else:
                    self.maindisplay[1] = msg.lcdwrite
            elif hasattr(msg, 'setpin'):
                if msg.setpin < len(button_state):
                    button_state[msg.setpin] = 1 if msg.val else 0
                sb.gpio_set(msg.setpin, msg.val)
        else:
            self.lastmsg = msg

    def handle_buttonevent(self, n, val):
        if n < len(BUTTON_MOM_CC):
            pxr.send_event(f"cc:{BUTTON_MIDICHANNEL}:{BUTTON_MOM_CC[n]}:{val}")
        if val and n < len(BUTTON_TOG_CC):
            button_state[n] ^= 1
            pxr.send_event(f"cc:{BUTTON_MIDICHANNEL}:{BUTTON_TOG_CC[n]}:{button_state[n]}")
            sb.gpio_set(n, button_state[n])

    def patchmode(self):
        pno = -1
        while True:
            sb.buttoncallback = self.handle_buttonevent
            if self.pno != pno:
                if pxr.patches:
                    pno = self.pno
                    self.maindisplay = [pxr.patches[pno], f"patch: {pno + 1}/{len(pxr.patches)}"]
                    warn = pxr.apply_patch(pno)
                else:
                    pno, self.pno = 0, 0
                    self.maindisplay = ["No patches", "patch 0/0"]
                    warn = pxr.apply_patch(None)
                if warn:
                    sb.lcd_write(self.maindisplay[0], 0, scroll=True)
                    sb.lcd_write('; '.join(warn), 1, scroll=True)
                    sb.waitfortap()
            lines = self.maindisplay[:]
            sb.lcd_write(lines[0], 0, scroll=True)
            sb.lcd_write(lines[1], 1, rjust=True)
            while True:
                if self.pno != pno: break
                if self.maindisplay != lines: break
                event = sb.update()
                if event == SB.RIGHT and pxr.patches:
                    self.pno = (self.pno + 1) % len(pxr.patches)
                elif event == SB.LEFT and pxr.patches:
                    self.pno = (self.pno - 1) % len(pxr.patches)
                elif event == SB.SELECT:
                    sb.buttoncallback = None
                    k = sb.choose_opt(['Load Bank', 'Save Bank', 'Save Patch', 'Delete Patch',
                                       'Open Soundfont', 'Effects..', 'System Menu..'], row=1)
                    if k == 0:
                        if self.load_bank(): pno = -1
                    elif k == 1:
                        self.save_bank()
                    elif k == 2:
                        sb.lcd_write("Save patch:", 0)
                        newname = sb.char_input(pxr.patches[self.pno])
                        if newname != '':
                            if newname != pxr.patches[self.pno]:
                                pxr.add_patch(newname, addlike=self.pno)
                            pxr.update_patch(newname)
                            self.pno = pxr.patches.index(newname)
                    elif k == 3:
                        if sb.confirm_choice('Delete', row=1):
                            pxr.delete_patch(self.pno)
                            self.pno = min(self.pno, len(pxr.patches) - 1)
                            pno = -1
                    elif k == 4:
                        if self.load_soundfont():
                            self.sfmode()
                            sb.lcd_write("loading patches ", 1, now=True)
                            sb.progresswheel_start()
                            pxr.load_bank()
                            sb.progresswheel_stop()
                            pno = -1
                    elif k == 5:
                        self.effects_menu()
                    elif k == 6:
                        self.system_menu()
                else: continue
                break

    def sfmode(self):
        i = 0
        warn = pxr.select_sfpreset(i)
        while True:
            p = pxr.sfpresets[i]
            sb.lcd_write(p.name, 0, scroll=True)
            if warn:
                sb.lcd_write('; '.join(warn), 1, scroll=True)
                sb.waitfortap()
                warn = []
            sb.lcd_write(f"preset {p.bank:03}:{p.prog:03}", 1, rjust=True)
            while True:
                event = sb.update()
                if event == SB.RIGHT:
                    i = (i + 1) % len(pxr.sfpresets)
                    warn = pxr.select_sfpreset(i)
                elif event == SB.LEFT:
                    i = (i - 1) % len(pxr.sfpresets)
                    warn = pxr.select_sfpreset(i)
                elif event == SB.SELECT:
                    k = sb.choose_opt(['Add as Patch', 'Open Soundfont', 'Back to Bank'], row=1)
                    if k == 0:
                        sb.lcd_write("Add as Patch:", 0)
                        newname = sb.char_input(p.name)
                        if newname == '': break
                        self.pno = pxr.add_patch(newname)
                        pxr.update_patch(newname)
                    elif k == 1:
                        if self.load_soundfont():
                            i = 0
                            warn = pxr.select_sfpreset(i)
                    elif k == 2: return
                elif event == SB.ESCAPE: return
                else: continue
                break

    def load_bank(self, bank=""):
        lastbank = pxr.currentbank
        lastpatch = pxr.patches[self.pno] if pxr.patches else ""
        if bank == "":
            if not pxr.banks:
                sb.lcd_write("no banks found", 1)
                sb.waitfortap(2)
                return False
            bank = choose_file(pxr.bankdir, '.yaml', pxr.bankdir / pxr.currentbank)
            if bank == "": return False
        sb.lcd_write(bank.name, 0, scroll=True, now=True)
        sb.lcd_write("loading patches ", 1, now=True)
        sb.progresswheel_start()
        try: pxr.load_bank(bank)
        except Exception as e:
            sb.progresswheel_stop()
            sb.lcd_write(f"bank load error: {exceptstr(e)}", 1, scroll=True)
            sb.waitfortap()
            return False
        sb.progresswheel_stop()
        pxr.write_config()
        if pxr.currentbank != lastbank:
            self.pno = 0
        else:
            if lastpatch in pxr.patches:
                self.pno = pxr.patches.index(lastpatch)
            elif self.pno >= len(pxr.patches):
                self.pno = 0
        return True

    def save_bank(self, bank=""):
        if bank == "":
            bank = choose_file(pxr.bankdir, '.yaml', pxr.bankdir / pxr.currentbank)
            if bank == "": return
            name = sb.char_input(bank.name)
            if name == "": return
            bank = bank.parent / name
        try: pxr.save_bank(bank.with_suffix('.yaml'))
        except Exception as e:
            sb.lcd_write(f"bank save error: {exceptstr(e)}", 1, scroll=True)
            sb.waitfortap()
        else:
            pxr.write_config()
            sb.lcd_write("bank saved", 1)
            sb.waitfortap(2)

    def load_soundfont(self, sfont=""):
        if sfont == "":
            if not pxr.soundfonts:
                sb.lcd_write("no soundfonts", 1)
                sb.waitfortap(2)
                return False
            sfont = choose_file(pxr.sfdir, '.sf2')
            if sfont == "": return False
        sb.lcd_write(sfont.name, 0, scroll=True, now=True)
        sb.lcd_write("loading presets ", 1, now=True)
        sb.progresswheel_start()
        if not pxr.load_soundfont(sfont):
            sb.progresswheel_stop()
            sb.lcd_write(f"Unable to load {str(pxr.soundfonts[s])}", 1, scroll=True)
            sb.waitfortap()
            return False
        sb.progresswheel_stop()
        return True

    def effects_menu(self):
        i=0
        fxmenu_info = (
# Name             fluidsetting              inc    min     max   format
('Reverb Size',   'synth.reverb.room-size',  0.1,   0.0,    1.0, '4.1f'),
('Reverb Damp',   'synth.reverb.damp',       0.1,   0.0,    1.0, '4.1f'),
('Rev. Width',    'synth.reverb.width',      0.5,   0.0,  100.0, '5.1f'),
('Rev. Level',    'synth.reverb.level',     0.01,  0.00,   1.00, '5.2f'),
('Chorus Voices', 'synth.chorus.nr',           1,     0,     99, '2d'),
('Chor. Level',   'synth.chorus.level',      0.1,   0.0,   10.0, '4.1f'),
('Chor. Speed',   'synth.chorus.speed',      0.1,   0.1,   21.0, '4.1f'),
('Chorus Depth',  'synth.chorus.depth',      0.1,   0.3,    5.0, '3.1f'),
('Gain',          'synth.gain',              0.1,   0.0,    5.0, '11.1f'))
        vals = [pxr.fluid_get(info[1]) for info in fxmenu_info]
        fxopts = [fxmenu_info[i][0] + ':' + format(vals[i], fxmenu_info[i][5]) for i in range(len(fxmenu_info))]
        while True:
            sb.lcd_write("Effects:", 0)
            i = sb.choose_opt(fxopts, i, row=1)
            if i < 0:
                break
            sb.lcd_write(fxopts[i], 0)
            newval = sb.choose_val(vals[i], *fxmenu_info[i][2:])
            if newval != None:
                pxr.fluid_set(fxmenu_info[i][1], newval, updatebank=True, patch=self.pno)
                vals[i] = newval
                fxopts[i] = fxmenu_info[i][0] + ':' + format(newval, fxmenu_info[i][5])

    def system_menu(self):
        sb.lcd_write("System Menu:", 0)
        k = sb.choose_opt(['Power Down', 'MIDI Devices', 'Wifi Settings', 'File Transfer', 'Update Device'], row=1)
        if k == 0:
            sb.lcd_write("Shutting down..", 0)
            sb.lcd_write("Wait 30s, unplug", 1, now=True)
            subprocess.run(['sudo', 'poweroff'])
        elif k == 1: self.midi_devices()
        elif k == 2: wifi_settings()
        elif k == 3: file_transfer()
        elif k == 4: update_device()

    def midi_devices(self):
        sb.lcd_write("MIDI Devices:", 0)
        readable = re.findall(" (\d+): '([^\n]*)'", subprocess.check_output(['aconnect', '-i'], encoding='ascii'))
        rports, names = list(zip(*readable))
        p = sb.choose_opt([*names, "MIDI monitor.."], row=1, scroll=True, timeout=0)
        if p < 0: return
        if 0 <= p < len(rports):
            sb.lcd_write("Connect to:", 0)
            writable = re.findall(" (\d+): '([^\n]*)'", subprocess.check_output(['aconnect', '-o'], encoding='ascii'))
            wports, names = list(zip(*writable))
            op = sb.choose_opt(names, row=1, scroll=True, timeout=0)
            if op < 0: return
            subprocess.run(['aconnect', rports[p], wports[op]])
        elif p == len(rports):
            sb.lcd_clear()
            sb.lcd_write("MIDI monitor:", 0)
            msg = self.lastmsg
            while not sb.waitfortap(0.1):
                if msg == self.lastmsg: continue
                msg = self.lastmsg
                if msg.type not in ('note', 'noteoff', 'cc', 'kpress', 'prog', 'pbend', 'cpress'): continue
                t = ('note', 'noteoff', 'cc', 'kpress', 'prog', 'pbend', 'cpress').index(msg.type)
                x = ("note", "noff", "  cc", "keyp", " prog", "pbend", "press")[t]
                if t < 4:
                    sb.lcd_write(f"ch{msg.chan + 1:<3}{x}{msg.par1:3}={msg.par2:<3}", 1)
                else:
                    sb.lcd_write(f"ch{msg.chan + 1:<3}{x}={msg.par1:<5}", 1)


sb = SB.StompBox()
sb.lcd_clear()
sb.lcd_write(f"version {patcher.VERSION}", 0, now=True)
sb.waitfortap(3)

cfgfile = sys.argv[1] if len(sys.argv) > 1 else 'SquishBox/squishboxconf.yaml'
try: pxr = patcher.Patcher(cfgfile)
except Exception as e:
    sb.lcd_write(f"bad config file: {exceptstr(e)}", 1, scroll=True)
    sys.exit(f"Unable to load config file\n{e}")

os.umask(0o002)
networks = []

mainapp = SquishBox()
