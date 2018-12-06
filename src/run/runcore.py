#! /usr/bin/env python
import sys
import os
import math
import rundef
import boot
sys.path.append(os.path.abspath(".."))
from gen import gencore
from gen import gendef
from fuse import fusedef
from ui import uidef
from ui import uivar
from mem import memdef
from boot import bltest
from boot import target
from utils import misc

def createTarget(device, exeBinRoot):
    # Build path to target directory and config file.
    if device == uidef.kMcuDevice_iMXRT102x:
        cpu = "MIMXRT1021"
    elif device == uidef.kMcuDevice_iMXRT105x:
        cpu = "MIMXRT1052"
    elif device == uidef.kMcuDevice_iMXRT106x:
        cpu = "MIMXRT1062"
    elif device == uidef.kMcuDevice_iMXRT1064:
        cpu = "MIMXRT1064"
    else:
        pass
    targetBaseDir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'targets', cpu)

    # Check for existing target directory.
    if not os.path.isdir(targetBaseDir):
        targetBaseDir = os.path.join(os.path.dirname(exeBinRoot), 'src', 'targets', cpu)
        if not os.path.isdir(targetBaseDir):
            raise ValueError("Missing target directory at path %s" % targetBaseDir)

    targetConfigFile = os.path.join(targetBaseDir, 'bltargetconfig.py')

    # Check for config file existence.
    if not os.path.isfile(targetConfigFile):
        raise RuntimeError("Missing target config file at path %s" % targetConfigFile)

    # Build locals dict by copying our locals and adjusting file path and name.
    targetConfig = locals().copy()
    targetConfig['__file__'] = targetConfigFile
    targetConfig['__name__'] = 'bltargetconfig'

    # Execute the target config script.
    execfile(targetConfigFile, globals(), targetConfig)

    # Create the target object.
    tgt = target.Target(**targetConfig)

    return tgt, targetBaseDir

##
# @brief
class secBootRun(gencore.secBootGen):

    def __init__(self, parent):
        gencore.secBootGen.__init__(self, parent)
        self.blhost = None
        self.sdphost = None
        self.tgt = None
        self.cpuDir = None
        self.sdphostVectorsDir = os.path.join(self.exeTopRoot, 'tools', 'sdphost', 'win', 'vectors')
        self.blhostVectorsDir = os.path.join(self.exeTopRoot, 'tools', 'blhost', 'win', 'vectors')

        self.bootDeviceMemId = None
        self.bootDeviceMemBase = None
        self.semcNandImageCopies = None
        self.isFlexspiNorErasedForImage = False

        self.mcuDeviceHabStatus = None
        self.mcuDeviceBtFuseSel = None
        self.mcuDeviceBeeKey0Sel = None
        self.mcuDeviceBeeKey1Sel = None

        self.comMemWriteUnit = 0
        self.comMemEraseUnit = 0
        self.comMemReadUnit = 0

        self.tgt, self.cpuDir = createTarget(self.mcuDevice, self.exeBinRoot)

    def getUsbid( self ):
        # Create the target object.
        tgt, cpuDir = createTarget(self.mcuDevice, self.exeBinRoot)
        return [tgt.romUsbVid, tgt.romUsbPid, tgt.flashloaderUsbVid, tgt.flashloaderUsbPid]

    def connectToDevice( self , connectStage):
        if connectStage == uidef.kConnectStage_Rom:
            # Create the target object.
            self.tgt, self.cpuDir = createTarget(self.mcuDevice, self.exeBinRoot)
            if self.isUartPortSelected:
                sdpPeripheral = 'sdp_uart'
                uartComPort = self.uartComPort
                uartBaudrate = int(self.uartBaudrate)
                usbVid = ''
                usbPid = ''
            elif self.isUsbhidPortSelected:
                sdpPeripheral = 'sdp_usb'
                uartComPort = ''
                uartBaudrate = ''
                usbVid = self.tgt.romUsbVid
                usbPid = self.tgt.romUsbPid
            else:
                pass
            self.sdphost = bltest.createBootloader(self.tgt,
                                                   self.sdphostVectorsDir,
                                                   sdpPeripheral,
                                                   uartBaudrate, uartComPort,
                                                   usbVid, usbPid)
        elif connectStage == uidef.kConnectStage_Flashloader:
            if self.isUartPortSelected:
                blPeripheral = 'uart'
                uartComPort = self.uartComPort
                uartBaudrate = int(self.uartBaudrate)
                usbVid = ''
                usbPid = ''
            elif self.isUsbhidPortSelected:
                blPeripheral = 'usb'
                uartComPort = ''
                uartBaudrate = ''
                usbVid = self.tgt.flashloaderUsbVid
                usbPid = self.tgt.flashloaderUsbPid
            else:
                pass
            self.blhost = bltest.createBootloader(self.tgt,
                                                  self.blhostVectorsDir,
                                                  blPeripheral,
                                                  uartBaudrate, uartComPort,
                                                  usbVid, usbPid,
                                                  True)
        elif connectStage == uidef.kConnectStage_Reset:
            self.tgt = None
        else:
            pass

    def pingRom( self ):
        status, results, cmdStr = self.sdphost.errorStatus()
        self.printLog(cmdStr)
        return (status == boot.status.kSDP_Status_HabEnabled or status == boot.status.kSDP_Status_HabDisabled)

    def _getDeviceRegisterBySdphost( self, regAddr, regName, needToShow=True):
        filename = 'readReg.dat'
        filepath = os.path.join(self.sdphostVectorsDir, filename)
        status, results, cmdStr = self.sdphost.readRegister(regAddr, 32, 4, filename)
        self.printLog(cmdStr)
        if (status == boot.status.kSDP_Status_HabEnabled or status == boot.status.kSDP_Status_HabDisabled):
            regVal = self.getVal32FromBinFile(filepath)
            if needToShow:
                self.printDeviceStatus(regName + " = " + str(hex(regVal)))
            return regVal
        else:
            if needToShow:
                self.printDeviceStatus(regName + " = --------")
            return None
        try:
            os.remove(filepath)
        except:
            pass

    def _readMcuDeviceRegisterUuid( self ):
        self._getDeviceRegisterBySdphost( rundef.kRegisterAddr_UUID1, 'OCOTP->B0W1 UUID[31:00]')
        self._getDeviceRegisterBySdphost( rundef.kRegisterAddr_UUID2, 'OCOTP->B0W2 UUID[63:32]')

    def _readMcuDeviceRegisterSrcSmbr( self ):
        self._getDeviceRegisterBySdphost( rundef.kRegisterAddr_SRC_SBMR1, 'SRC->SMBR1')
        self._getDeviceRegisterBySdphost( rundef.kRegisterAddr_SRC_SBMR2, 'SRC->SMBR2')

    def getMcuDeviceInfoViaRom( self ):
        self.printDeviceStatus("--------MCU device Register----------")
        self._readMcuDeviceRegisterUuid()
        self._readMcuDeviceRegisterSrcSmbr()

    def getMcuDeviceHabStatus( self ):
        secConfig = self._getDeviceRegisterBySdphost( rundef.kRegisterAddr_SRC_SBMR2, '', False)
        if secConfig != None:
            self.mcuDeviceHabStatus = ((secConfig & rundef.kRegisterMask_SecConfig) >> rundef.kRegisterShift_SecConfig)
            if self.mcuDeviceHabStatus == fusedef.kHabStatus_FAB:
                self.printDeviceStatus('HAB status = FAB')
            elif self.mcuDeviceHabStatus == fusedef.kHabStatus_Open:
                self.printDeviceStatus('HAB status = Open')
            elif self.mcuDeviceHabStatus == fusedef.kHabStatus_Closed0 or self.mcuDeviceHabStatus == fusedef.kHabStatus_Closed1:
                self.printDeviceStatus('HAB status = Closed')
            else:
                pass

    def jumpToFlashloader( self ):
        flashloaderBinFile = None
        if self.mcuDeviceHabStatus == fusedef.kHabStatus_Closed0 or self.mcuDeviceHabStatus == fusedef.kHabStatus_Closed1:
            flashloaderSrecFile = os.path.join(self.cpuDir, 'flashloader.srec')
            flashloaderBinFile = self.genSignedFlashloader(flashloaderSrecFile)
            if flashloaderBinFile == None:
                return False
        elif self.mcuDeviceHabStatus == fusedef.kHabStatus_FAB or self.mcuDeviceHabStatus == fusedef.kHabStatus_Open:
            flashloaderBinFile = os.path.join(self.cpuDir, 'ivt_flashloader.bin')
        else:
            pass
        status, results, cmdStr = self.sdphost.writeFile(self.tgt.flashloaderLoadAddr, flashloaderBinFile)
        self.printLog(cmdStr)
        if status != boot.status.kSDP_Status_HabEnabled and status != boot.status.kSDP_Status_HabDisabled:
            return False
        status, results, cmdStr = self.sdphost.jumpAddress(self.tgt.flashloaderJumpAddr)
        self.printLog(cmdStr)
        if status != boot.status.kSDP_Status_HabEnabled and status != boot.status.kSDP_Status_HabDisabled:
            return False
        return True

    def pingFlashloader( self ):
        status, results, cmdStr = self.blhost.getProperty(boot.properties.kPropertyTag_CurrentVersion)
        self.printLog(cmdStr)
        return (status == boot.status.kStatus_Success)

    def readMcuDeviceFuseByBlhost( self, fuseIndex, fuseName, needToShow=True):
        status, results, cmdStr = self.blhost.efuseReadOnce(fuseIndex)
        self.printLog(cmdStr)
        if (status == boot.status.kStatus_Success):
            if needToShow:
                self.printDeviceStatus(fuseName + " = " + str(hex(results[1])))
            return results[1]
        else:
            if needToShow:
                self.printDeviceStatus(fuseName + " = --------")
            return None

    def _readMcuDeviceFuseTester( self ):
        self.readMcuDeviceFuseByBlhost(fusedef.kEfuseIndex_TESTER0, '(0x410) TESTER0')
        self.readMcuDeviceFuseByBlhost(fusedef.kEfuseIndex_TESTER1, '(0x420) TESTER1')
        self.readMcuDeviceFuseByBlhost(fusedef.kEfuseIndex_TESTER2, '(0x430) TESTER2')
        self.readMcuDeviceFuseByBlhost(fusedef.kEfuseIndex_TESTER3, '(0x440) TESTER3')

    def _readMcuDeviceFuseBootCfg( self ):
        self.readMcuDeviceFuseByBlhost(fusedef.kEfuseIndex_BOOT_CFG0, '(0x450) BOOT_CFG0')
        self.readMcuDeviceFuseByBlhost(fusedef.kEfuseIndex_BOOT_CFG1, '(0x460) BOOT_CFG1')
        self.readMcuDeviceFuseByBlhost(fusedef.kEfuseIndex_BOOT_CFG2, '(0x470) BOOT_CFG2')

    def _genOtpmkDekFile( self, otpmk4, otpmk5, otpmk6, otpmk7 ):
        try:
            os.remove(self.otpmkDekFilename)
        except:
            pass
        self.fillVal32IntoBinFile(self.otpmkDekFilename, otpmk4)
        self.fillVal32IntoBinFile(self.otpmkDekFilename, otpmk5)
        self.fillVal32IntoBinFile(self.otpmkDekFilename, otpmk6)
        self.fillVal32IntoBinFile(self.otpmkDekFilename, otpmk7)

    def _readMcuDeviceFuseOtpmkDek( self ):
        otpmk4 = self.readMcuDeviceFuseByBlhost(fusedef.kEfuseIndex_OTPMK4, '', False)
        otpmk5 = self.readMcuDeviceFuseByBlhost(fusedef.kEfuseIndex_OTPMK5, '', False)
        otpmk6 = self.readMcuDeviceFuseByBlhost(fusedef.kEfuseIndex_OTPMK6, '', False)
        otpmk7 = self.readMcuDeviceFuseByBlhost(fusedef.kEfuseIndex_OTPMK7, '', False)
        if otpmk4 != None and otpmk5 != None and otpmk6 != None and otpmk7 != None:
            self._genOtpmkDekFile(otpmk4, otpmk5, otpmk6, otpmk7)

    def _readMcuDeviceFuseSrk( self ):
        self.readMcuDeviceFuseByBlhost(fusedef.kEfuseIndex_SRK0, '(0x580) SRK0')
        self.readMcuDeviceFuseByBlhost(fusedef.kEfuseIndex_SRK1, '(0x590) SRK1')
        self.readMcuDeviceFuseByBlhost(fusedef.kEfuseIndex_SRK2, '(0x5A0) SRK2')
        self.readMcuDeviceFuseByBlhost(fusedef.kEfuseIndex_SRK3, '(0x5B0) SRK3')
        self.readMcuDeviceFuseByBlhost(fusedef.kEfuseIndex_SRK4, '(0x5C0) SRK4')
        self.readMcuDeviceFuseByBlhost(fusedef.kEfuseIndex_SRK5, '(0x5D0) SRK5')
        self.readMcuDeviceFuseByBlhost(fusedef.kEfuseIndex_SRK6, '(0x5E0) SRK6')
        self.readMcuDeviceFuseByBlhost(fusedef.kEfuseIndex_SRK7, '(0x5F0) SRK7')

    def _readMcuDeviceFuseSwGp2( self ):
        self.readMcuDeviceFuseByBlhost(fusedef.kEfuseIndex_SW_GP2_0, '(0x690) SW_GP2_0')
        self.readMcuDeviceFuseByBlhost(fusedef.kEfuseIndex_SW_GP2_1, '(0x6A0) SW_GP2_1')
        self.readMcuDeviceFuseByBlhost(fusedef.kEfuseIndex_SW_GP2_2, '(0x6B0) SW_GP2_2')
        self.readMcuDeviceFuseByBlhost(fusedef.kEfuseIndex_SW_GP2_3, '(0x6C0) SW_GP2_3')

    def getMcuDeviceInfoViaFlashloader( self ):
        self.printDeviceStatus("--------MCU device eFusemap--------")
        #self._readMcuDeviceFuseTester()
        self._readMcuDeviceFuseBootCfg()
        #self._readMcuDeviceFuseOtpmkDek()
        #self._readMcuDeviceFuseSrk()
        #self._readMcuDeviceFuseSwGp2()

    def getMcuDeviceBtFuseSel( self ):
        btFuseSel = self.readMcuDeviceFuseByBlhost(fusedef.kEfuseLocation_BtFuseSel, '', False)
        if btFuseSel != None:
            self.mcuDeviceBtFuseSel = ((btFuseSel & fusedef.kEfuseMask_BtFuseSel) >> fusedef.kEfuseShift_BtFuseSel)
            if self.mcuDeviceBtFuseSel == 0:
                self.printDeviceStatus('BT_FUSE_SEL = 1\'b0')
                self.printDeviceStatus('  When BMOD[1:0] = 2\'b00 (Boot From Fuses), It means there is no application in boot device, MCU will enter serial downloader mode directly')
                self.printDeviceStatus('  When BMOD[1:0] = 2\'b10 (Internal Boot), It means MCU will boot application according to both BOOT_CFGx pins and Fuse BOOT_CFGx')
            elif self.mcuDeviceBtFuseSel == 1:
                self.printDeviceStatus('BT_FUSE_SEL = 1\'b1')
                self.printDeviceStatus('  When BMOD[1:0] = 2\'b00 (Boot From Fuses), It means there is application in boot device, MCU will boot application according to Fuse BOOT_CFGx')
                self.printDeviceStatus('  When BMOD[1:0] = 2\'b10 (Internal Boot), It means MCU will boot application according to Fuse BOOT_CFGx only')
            else:
                pass

    def _prepareForBootDeviceOperation ( self ):
        if self.bootDevice == uidef.kBootDevice_FlexspiNor:
            self.bootDeviceMemId = rundef.kBootDeviceMemId_FlexspiNor
            self.bootDeviceMemBase = self.tgt.flexspiNorMemBase
        elif self.bootDevice == uidef.kBootDevice_FlexspiNand:
            self.bootDeviceMemId = rundef.kBootDeviceMemId_FlexspiNand
            self.bootDeviceMemBase = rundef.kBootDeviceMemBase_FlexspiNand
        elif self.bootDevice == uidef.kBootDevice_SemcNor:
            self.bootDeviceMemId = rundef.kBootDeviceMemId_SemcNor
            self.bootDeviceMemBase = rundef.kBootDeviceMemBase_SemcNor
        elif self.bootDevice == uidef.kBootDevice_SemcNand:
            self.bootDeviceMemId = rundef.kBootDeviceMemId_SemcNand
            self.bootDeviceMemBase = rundef.kBootDeviceMemBase_SemcNand
        elif self.bootDevice == uidef.kBootDevice_UsdhcSd:
            self.bootDeviceMemId = rundef.kBootDeviceMemId_UsdhcSd
            self.bootDeviceMemBase = rundef.kBootDeviceMemBase_UsdhcSd
        elif self.bootDevice == uidef.kBootDevice_UsdhcMmc:
            self.bootDeviceMemId = rundef.kBootDeviceMemId_UsdhcMmc
            self.bootDeviceMemBase = rundef.kBootDeviceMemBase_UsdhcMmc
        elif self.bootDevice == uidef.kBootDevice_LpspiNor:
            self.bootDeviceMemId = rundef.kBootDeviceMemId_LpspiNor
            self.bootDeviceMemBase = rundef.kBootDeviceMemBase_LpspiNor
        else:
            pass

    def _getSemcNandDeviceInfo ( self ):
        filename = 'semcNandFcb.dat'
        filepath = os.path.join(self.blhostVectorsDir, filename)
        status, results, cmdStr = self.blhost.readMemory(self.bootDeviceMemBase + rundef.kSemcNandFcbInfo_StartAddr, rundef.kSemcNandFcbInfo_Length, filename, self.bootDeviceMemId)
        self.printLog(cmdStr)
        if status != boot.status.kStatus_Success:
            return False
        fingerprint = self.getVal32FromBinFile(filepath, rundef.kSemcNandFcbOffset_Fingerprint)
        semcTag = self.getVal32FromBinFile(filepath, rundef.kSemcNandFcbOffset_SemcTag)
        if fingerprint == rundef.kSemcNandFcbTag_Fingerprint and semcTag == rundef.kSemcNandFcbTag_Semc:
            firmwareCopies = self.getVal32FromBinFile(filepath, rundef.kSemcNandFcbOffset_FirmwareCopies)
            pageByteSize = self.getVal32FromBinFile(filepath, rundef.kSemcNandFcbOffset_PageByteSize)
            pagesInBlock = self.getVal32FromBinFile(filepath, rundef.kSemcNandFcbOffset_PagesInBlock)
            blocksInPlane = self.getVal32FromBinFile(filepath, rundef.kSemcNandFcbOffset_BlocksInPlane)
            planesInDevice = self.getVal32FromBinFile(filepath, rundef.kSemcNandFcbOffset_PlanesInDevice)
            self.printDeviceStatus("Page Size (bytes) = " + str(hex(pageByteSize)))
            self.printDeviceStatus("Pages In Block    = " + str(hex(pagesInBlock)))
            self.printDeviceStatus("Blocks In Plane   = " + str(hex(blocksInPlane)))
            self.printDeviceStatus("Planes In Device  = " + str(hex(planesInDevice)))
            self.semcNandImageCopies = firmwareCopies
            self.comMemWriteUnit = pageByteSize
            self.comMemEraseUnit = pageByteSize * pagesInBlock
            self.comMemReadUnit = pageByteSize
        else:
            self.printDeviceStatus("Page Size (bytes) = --------")
            self.printDeviceStatus("Pages In Block    = --------")
            self.printDeviceStatus("Blocks In Plane   = --------")
            self.printDeviceStatus("Planes In Device  = --------")
            return False
        try:
            os.remove(filepath)
        except:
            pass
        return True

    def _getFlexspiNorDeviceInfo ( self ):
        filename = 'flexspiNorCfg.dat'
        filepath = os.path.join(self.blhostVectorsDir, filename)
        status, results, cmdStr = self.blhost.readMemory(self.bootDeviceMemBase + rundef.kFlexspiNorCfgInfo_StartAddr, rundef.kFlexspiNorCfgInfo_Length, filename, self.bootDeviceMemId)
        self.printLog(cmdStr)
        if status != boot.status.kStatus_Success:
            return False
        flexspiTag = self.getVal32FromBinFile(filepath, rundef.kFlexspiNorCfgOffset_FlexspiTag)
        if flexspiTag == rundef.kFlexspiNorCfgTag_Flexspi:
            pageByteSize = self.getVal32FromBinFile(filepath, rundef.kFlexspiNorCfgOffset_PageByteSize)
            sectorByteSize = self.getVal32FromBinFile(filepath, rundef.kFlexspiNorCfgOffset_SectorByteSize)
            blockByteSize = self.getVal32FromBinFile(filepath, rundef.kFlexspiNorCfgOffset_BlockByteSize)
            self.printDeviceStatus("Page Size (bytes)   = " + str(hex(pageByteSize)))
            self.printDeviceStatus("Sector Size (bytes) = " + str(hex(sectorByteSize)))
            self.printDeviceStatus("Block Size (bytes)  = " + str(hex(blockByteSize)))
            self.comMemWriteUnit = pageByteSize
            self.comMemEraseUnit = sectorByteSize
            self.comMemReadUnit = pageByteSize
        else:
            self.printDeviceStatus("Page Size (bytes)   = --------")
            self.printDeviceStatus("Sector Size (bytes) = --------")
            self.printDeviceStatus("Block Size (bytes)  = --------")
            return False
        try:
            os.remove(filepath)
        except:
            pass
        return True

    def _getLpspiNorDeviceInfo ( self ):
        pageByteSize = 0
        sectorByteSize = 0
        totalByteSize = 0
        lpspiNorOpt0, lpspiNorOpt1 = uivar.getBootDeviceConfiguration(self.bootDevice)
        val = (lpspiNorOpt0 & 0x0000000F) >> 0
        if val <= 2:
            pageByteSize = int(math.pow(2, val + 8))
        else:
            pageByteSize = int(math.pow(2, val + 2))
        val = (lpspiNorOpt0 & 0x000000F0) >> 4
        if val <= 1:
            sectorByteSize = int(math.pow(2, val + 12))
        else:
            sectorByteSize = int(math.pow(2, val + 13))
        val = (lpspiNorOpt0 & 0x00000F00) >> 8
        if val <= 11:
            totalByteSize = int(math.pow(2, val + 19))
        else:
            totalByteSize = int(math.pow(2, val + 3))
        self.printDeviceStatus("Page Size (bytes)   = " + str(hex(pageByteSize)))
        self.printDeviceStatus("Sector Size (bytes) = " + str(hex(sectorByteSize)))
        self.printDeviceStatus("Total Size (bytes)  = " + str(hex(totalByteSize)))
        self.comMemWriteUnit = pageByteSize
        self.comMemEraseUnit = sectorByteSize
        self.comMemReadUnit = pageByteSize
        return True

    def getBootDeviceInfoViaFlashloader ( self ):
        if self.bootDevice == uidef.kBootDevice_SemcNand:
            self.printDeviceStatus("--------SEMC NAND memory----------")
            self._getSemcNandDeviceInfo()
        elif self.bootDevice == uidef.kBootDevice_FlexspiNor:
            self.printDeviceStatus("--------FlexSPI NOR memory--------")
            self._getFlexspiNorDeviceInfo()
        elif self.bootDevice == uidef.kBootDevice_LpspiNor:
            self.printDeviceStatus("--------LPSPI NOR/EEPROM memory---")
            self._getLpspiNorDeviceInfo()
        else:
            pass

    def _eraseFlexspiNorForConfigBlockLoading( self ):
        status, results, cmdStr = self.blhost.flashEraseRegion(self.tgt.flexspiNorMemBase, rundef.kFlexspiNorCfgInfo_Length, rundef.kBootDeviceMemId_FlexspiNor)
        self.printLog(cmdStr)
        return (status == boot.status.kStatus_Success)

    def _programFlexspiNorConfigBlock ( self ):
        #if not self.tgt.isSipFlexspiNorDevice:
        if True:
            # 0xf000000f is the tag to notify Flashloader to program FlexSPI NOR config block to the start of device
            status, results, cmdStr = self.blhost.fillMemory(rundef.kRamFreeSpaceStart_LoadCfgBlock, 0x4, rundef.kFlexspiNorCfgInfo_Notify)
            self.printLog(cmdStr)
            if status != boot.status.kStatus_Success:
                return False
            status, results, cmdStr = self.blhost.configureMemory(self.bootDeviceMemId, rundef.kRamFreeSpaceStart_LoadCfgBlock)
            self.printLog(cmdStr)
            return (status == boot.status.kStatus_Success)
        else:
            status, results, cmdStr = self.blhost.writeMemory(self.bootDeviceMemBase, os.path.join(self.cpuDir, 'sip_flash_config.bin'), self.bootDeviceMemId)
            self.printLog(cmdStr)
            return (status == boot.status.kStatus_Success)

    def configureBootDevice ( self ):
        self._prepareForBootDeviceOperation()
        if self.bootDevice == uidef.kBootDevice_SemcNand:
            semcNandOpt, semcNandFcbOpt, semcNandImageInfo = uivar.getBootDeviceConfiguration(self.bootDevice)
            status, results, cmdStr = self.blhost.fillMemory(rundef.kRamFreeSpaceStart_LoadCommOpt, 0x4, semcNandOpt)
            self.printLog(cmdStr)
            if status != boot.status.kStatus_Success:
                return False
            status, results, cmdStr = self.blhost.fillMemory(rundef.kRamFreeSpaceStart_LoadCommOpt + 4, 0x4, semcNandFcbOpt)
            self.printLog(cmdStr)
            if status != boot.status.kStatus_Success:
                return False
            for i in range(len(semcNandImageInfo)):
                if semcNandImageInfo[i] != None:
                    status, results, cmdStr = self.blhost.fillMemory(rundef.kRamFreeSpaceStart_LoadCommOpt + 8 + i * 4, 0x4, semcNandImageInfo[i])
                    self.printLog(cmdStr)
                    if status != boot.status.kStatus_Success:
                        return False
                else:
                    break
            status, results, cmdStr = self.blhost.configureMemory(self.bootDeviceMemId, rundef.kRamFreeSpaceStart_LoadCommOpt)
            self.printLog(cmdStr)
            if status != boot.status.kStatus_Success:
                return False
        elif self.bootDevice == uidef.kBootDevice_FlexspiNor:
            flexspiNorOpt0, flexspiNorOpt1 = uivar.getBootDeviceConfiguration(self.bootDevice)
            status, results, cmdStr = self.blhost.fillMemory(rundef.kRamFreeSpaceStart_LoadCommOpt, 0x4, flexspiNorOpt0)
            self.printLog(cmdStr)
            if status != boot.status.kStatus_Success:
                return False
            status, results, cmdStr = self.blhost.fillMemory(rundef.kRamFreeSpaceStart_LoadCommOpt + 4, 0x4, flexspiNorOpt1)
            self.printLog(cmdStr)
            if status != boot.status.kStatus_Success:
                return False
            status, results, cmdStr = self.blhost.configureMemory(self.bootDeviceMemId, rundef.kRamFreeSpaceStart_LoadCommOpt)
            self.printLog(cmdStr)
            if status != boot.status.kStatus_Success:
                return False
            if not self._eraseFlexspiNorForConfigBlockLoading():
                return False
            if not self._programFlexspiNorConfigBlock():
                return False
        elif self.bootDevice == uidef.kBootDevice_LpspiNor:
            lpspiNorOpt0, lpspiNorOpt1 = uivar.getBootDeviceConfiguration(self.bootDevice)
            status, results, cmdStr = self.blhost.fillMemory(rundef.kRamFreeSpaceStart_LoadCommOpt, 0x4, lpspiNorOpt0)
            self.printLog(cmdStr)
            if status != boot.status.kStatus_Success:
                return False
            status, results, cmdStr = self.blhost.fillMemory(rundef.kRamFreeSpaceStart_LoadCommOpt + 4, 0x4, lpspiNorOpt1)
            self.printLog(cmdStr)
            if status != boot.status.kStatus_Success:
                return False
            status, results, cmdStr = self.blhost.configureMemory(self.bootDeviceMemId, rundef.kRamFreeSpaceStart_LoadCommOpt)
            self.printLog(cmdStr)
            if status != boot.status.kStatus_Success:
                return False
        else:
            pass
        return True

    def _showOtpmkDek( self ):
        if os.path.isfile(self.otpmkDekFilename):
            self.clearOtpmkDekData()
            keyWords = gendef.kSecKeyLengthInBits_DEK / 32
            for i in range(keyWords):
                val32 = self.getVal32FromBinFile(self.otpmkDekFilename, (i * 4))
                self.printOtpmkDekData(self.getFormattedHexValue(val32))

    def _eraseFlexspiNorForImageLoading( self ):
        imageLen = os.path.getsize(self.destAppFilename)
        memEraseLen = misc.align_up(imageLen, self.comMemEraseUnit)
        status, results, cmdStr = self.blhost.flashEraseRegion(self.tgt.flexspiNorMemBase, memEraseLen, rundef.kBootDeviceMemId_FlexspiNor)
        self.printLog(cmdStr)
        if status != boot.status.kStatus_Success:
            return False
        self.isFlexspiNorErasedForImage = True
        return True

    def prepareForFixedOtpmkEncryption( self ):
        self._prepareForBootDeviceOperation()
        #self._showOtpmkDek()
        if not self._eraseFlexspiNorForImageLoading():
            return False
        otpmkKeyOpt, otpmkEncryptedRegionStart, otpmkEncryptedRegionLength = uivar.getAdvancedSettings(uidef.kAdvancedSettings_OtpmkKey)
        # Prepare PRDB options
        #---------------------------------------------------------------------------
        # 0xe0120000 is an option for PRDB contruction and image encryption
        # bit[31:28] tag, fixed to 0x0E
        # bit[27:24] Key source, fixed to 0 for A0 silicon
        # bit[23:20] AES mode: 1 - CTR mode
        # bit[19:16] Encrypted region count
        # bit[15:00] reserved in A0
        #---------------------------------------------------------------------------
        encryptedRegionCnt = (otpmkKeyOpt & 0x000F0000) >> 16
        if encryptedRegionCnt == 0:
            otpmkKeyOpt = (otpmkKeyOpt & 0xFFF0FFFF) | (0x1 << 16)
            encryptedRegionCnt = 1
            otpmkEncryptedRegionStart[0] = self.tgt.flexspiNorMemBase + gendef.kIvtOffset_NOR
            otpmkEncryptedRegionLength[0] = misc.align_up(os.path.getsize(self.destAppFilename), gendef.kSecFacRegionAlignedUnit) - gendef.kIvtOffset_NOR
        else:
            pass
        status, results, cmdStr = self.blhost.fillMemory(rundef.kRamFreeSpaceStart_LoadPrdbOpt, 0x4, otpmkKeyOpt)
        self.printLog(cmdStr)
        if status != boot.status.kStatus_Success:
            return False
        for i in range(encryptedRegionCnt):
            status, results, cmdStr = self.blhost.fillMemory(rundef.kRamFreeSpaceStart_LoadPrdbOpt + i * 8 + 4, 0x4, otpmkEncryptedRegionStart[i])
            self.printLog(cmdStr)
            if status != boot.status.kStatus_Success:
                return False
            status, results, cmdStr = self.blhost.fillMemory(rundef.kRamFreeSpaceStart_LoadPrdbOpt + i * 8 + 8, 0x4, otpmkEncryptedRegionLength[i])
            self.printLog(cmdStr)
            if status != boot.status.kStatus_Success:
                return False
        status, results, cmdStr = self.blhost.configureMemory(self.bootDeviceMemId, rundef.kRamFreeSpaceStart_LoadPrdbOpt)
        self.printLog(cmdStr)
        if status != boot.status.kStatus_Success:
            return False
        if not self._programFlexspiNorConfigBlock():
            return False
        self.invalidateStepButtonColor(uidef.kSecureBootSeqStep_PrepBee)
        return True

    def _isDeviceFuseSrkRegionReadyForBurn( self, srkFuseFilename ):
        isReady = True
        isBlank = True
        keyWords = gendef.kSecKeyLengthInBits_SRK / 32
        for i in range(keyWords):
            srk = self.readMcuDeviceFuseByBlhost(fusedef.kEfuseIndex_SRK0 + i, '(' + str(hex(0x580 + i * 0x10)) + ') ' + 'SRK' + str(i), False)
            if srk != None and srk != 0:
                isBlank = False
                val32 = self.getVal32FromBinFile(srkFuseFilename, (i * 4))
                if srk != val32:
                    isReady = False
                    break
        return isReady, isBlank

    def burnMcuDeviceFuseByBlhost( self, fuseIndex, fuseValue):
        status, results, cmdStr = self.blhost.efuseProgramOnce(fuseIndex, self.getFormattedFuseValue(fuseValue))
        self.printLog(cmdStr)

    def burnSrkData ( self ):
        if os.path.isfile(self.srkFuseFilename):
            isReady, isBlank = self._isDeviceFuseSrkRegionReadyForBurn(self.srkFuseFilename)
            if isReady:
                if isBlank:
                    keyWords = gendef.kSecKeyLengthInBits_SRK / 32
                    for i in range(keyWords):
                        val32 = self.getVal32FromBinFile(self.srkFuseFilename, (i * 4))
                        self.burnMcuDeviceFuseByBlhost(fusedef.kEfuseIndex_SRK0 + i, val32)
                self.invalidateStepButtonColor(uidef.kSecureBootSeqStep_ProgSrk)
                return True
            else:
                self.popupMsgBox('Fuse SRK Region has been burned, it is program-once!')
        else:
            self.popupMsgBox('Super Root Keys hasn\'t been generated!')
        return False

    def _isDeviceFuseSwGp2RegionReadyForBurn( self, swgp2DekFilename ):
        isReady = True
        isBlank = True
        keyWords = gendef.kSecKeyLengthInBits_DEK / 32
        for i in range(keyWords):
            dek = self.readMcuDeviceFuseByBlhost(fusedef.kEfuseIndex_SW_GP2_0 + i, '(' + str(hex(0x690 + i * 0x10)) + ') ' + 'SW_GP2_' + str(i), False)
            if dek != None and dek != 0:
                isBlank = False
                val32 = self.getVal32FromBinFile(swgp2DekFilename, (i * 4))
                if dek != val32:
                    isReady = False
                    break
        return isReady, isBlank

    def _isDeviceFuseGp4RegionReadyForBurn( self, gp4DekFilename ):
        isReady = True
        isBlank = True
        keyWords = gendef.kSecKeyLengthInBits_DEK / 32
        for i in range(keyWords):
            dek = self.readMcuDeviceFuseByBlhost(fusedef.kEfuseIndex_GP4_0 + i, '(' + str(hex(0x8C0 + i * 0x10)) + ') ' + 'GP4_' + str(i), False)
            if dek != None and dek != 0:
                isBlank = False
                val32 = self.getVal32FromBinFile(gp4DekFilename, (i * 4))
                if dek != val32:
                    isReady = False
                    break
        return isReady, isBlank

    def burnBeeDekData ( self ):
        needToBurnSwGp2 = False
        needToBurnGp4 = False
        swgp2DekFilename = None
        gp4DekFilename = None
        userKeyCtrlDict, userKeyCmdDict = uivar.getAdvancedSettings(uidef.kAdvancedSettings_UserKeys)
        if userKeyCtrlDict['engine_sel'] == uidef.kUserEngineSel_Engine1 or userKeyCtrlDict['engine_sel'] == uidef.kUserEngineSel_BothEngines:
            if userKeyCtrlDict['engine1_key_src'] == uidef.kUserKeySource_SW_GP2:
                needToBurnSwGp2 = True
                swgp2DekFilename = self.beeDek1Filename
            elif userKeyCtrlDict['engine1_key_src'] == uidef.kUserKeySource_GP4:
                needToBurnGp4 = True
                gp4DekFilename = self.beeDek1Filename
            else:
                pass
        if userKeyCtrlDict['engine_sel'] == uidef.kUserEngineSel_Engine0 or userKeyCtrlDict['engine_sel'] == uidef.kUserEngineSel_BothEngines:
            if userKeyCtrlDict['engine0_key_src'] == uidef.kUserKeySource_SW_GP2:
                needToBurnSwGp2 = True
                swgp2DekFilename = self.beeDek0Filename
            elif userKeyCtrlDict['engine0_key_src'] == uidef.kUserKeySource_GP4:
                needToBurnGp4 = True
                gp4DekFilename = self.beeDek0Filename
            else:
                pass
        keyWords = gendef.kSecKeyLengthInBits_DEK / 32
        if needToBurnSwGp2:
            isReady, isBlank = self._isDeviceFuseSwGp2RegionReadyForBurn(swgp2DekFilename)
            if isReady:
                if isBlank:
                    for i in range(keyWords):
                        val32 = self.getVal32FromBinFile(swgp2DekFilename, (i * 4))
                        self.burnMcuDeviceFuseByBlhost(fusedef.kEfuseIndex_SW_GP2_0 + i, val32)
            else:
                self.popupMsgBox('Fuse SW_GP2 Region has been burned, it is program-once!')
                return False
        else:
            pass
        if needToBurnGp4:
            isReady, isBlank = self._isDeviceFuseGp4RegionReadyForBurn(gp4DekFilename)
            if isReady:
                if isBlank:
                    for i in range(keyWords):
                        val32 = self.getVal32FromBinFile(gp4DekFilename, (i * 4))
                        self.burnMcuDeviceFuseByBlhost(fusedef.kEfuseIndex_GP4_0 + i, val32)
            else:
                self.popupMsgBox('Fuse GP4 Region has been burned, it is program-once!')
                return False
        else:
            pass
        self.invalidateStepButtonColor(uidef.kSecureBootSeqStep_OperBee)
        return True

    def _genDestEncAppFileWithoutCfgBlock( self ):
        destEncAppPath, destEncAppFile = os.path.split(self.destEncAppFilename)
        destEncAppName, destEncAppType = os.path.splitext(destEncAppFile)
        destEncAppName += '_nocfgblock'
        self.destEncAppNoCfgBlockFilename = os.path.join(destEncAppPath, destEncAppName + destEncAppType)
        imageLen = os.path.getsize(self.destEncAppFilename)
        imageData = None
        with open(self.destEncAppFilename, 'rb') as fileObj:
            imageData = fileObj.read(imageLen)
            if len(imageData) > rundef.kFlexspiNorCfgInfo_Length:
                imageData = imageData[rundef.kFlexspiNorCfgInfo_Length:len(imageData)]
            fileObj.close()
        with open(self.destEncAppNoCfgBlockFilename, 'wb') as fileObj:
            fileObj.write(imageData)
            fileObj.close()

    def flashBootableImage ( self ):
        self._prepareForBootDeviceOperation()
        imageLen = os.path.getsize(self.destAppFilename)
        if self.bootDevice == uidef.kBootDevice_SemcNand:
            semcNandOpt, semcNandFcbOpt, imageInfo = uivar.getBootDeviceConfiguration(self.bootDevice)
            memEraseLen = misc.align_up(imageLen, self.semcNandBlockSize)
            for i in range(self.semcNandImageCopies):
                imageLoadAddr = self.bootDeviceMemBase + (imageInfo[i] >> 16) * self.semcNandBlockSize
                status, results, cmdStr = self.blhost.flashEraseRegion(imageLoadAddr, memEraseLen, self.bootDeviceMemId)
                self.printLog(cmdStr)
                if status != boot.status.kStatus_Success:
                    return False
                status, results, cmdStr = self.blhost.writeMemory(imageLoadAddr, self.destAppFilename, self.bootDeviceMemId)
                self.printLog(cmdStr)
                if status != boot.status.kStatus_Success:
                    return False
        elif self.bootDevice == uidef.kBootDevice_FlexspiNor:
            if not self.isFlexspiNorErasedForImage:
                if not self._eraseFlexspiNorForImageLoading():
                    return False
                if self.secureBootType == uidef.kSecureBootType_Development or \
                   self.secureBootType == uidef.kSecureBootType_HabAuth or \
                   (self.secureBootType == uidef.kSecureBootType_BeeCrypto and self.keyStorageRegion == uidef.kKeyStorageRegion_FlexibleUserKeys):
                    if not self._programFlexspiNorConfigBlock():
                        self.isFlexspiNorErasedForImage = False
                        return False
            if self.secureBootType == uidef.kSecureBootType_BeeCrypto and self.keyStorageRegion == uidef.kKeyStorageRegion_FlexibleUserKeys:
                self._genDestEncAppFileWithoutCfgBlock()
                imageLoadAddr = self.bootDeviceMemBase + rundef.kFlexspiNorCfgInfo_Length
                status, results, cmdStr = self.blhost.writeMemory(imageLoadAddr, self.destEncAppNoCfgBlockFilename, self.bootDeviceMemId)
                self.printLog(cmdStr)
            else:
                imageLoadAddr = self.bootDeviceMemBase + gendef.kIvtOffset_NOR
                status, results, cmdStr = self.blhost.writeMemory(imageLoadAddr, self.destAppNoPaddingFilename, self.bootDeviceMemId)
                self.printLog(cmdStr)
            self.isFlexspiNorErasedForImage = False
            if status != boot.status.kStatus_Success:
                return False
        elif self.bootDevice == uidef.kBootDevice_LpspiNor:
            memEraseLen = misc.align_up(imageLen, self.comMemEraseUnit)
            imageLoadAddr = self.bootDeviceMemBase
            status, results, cmdStr = self.blhost.flashEraseRegion(imageLoadAddr, memEraseLen, self.bootDeviceMemId)
            self.printLog(cmdStr)
            if status != boot.status.kStatus_Success:
                return False
            status, results, cmdStr = self.blhost.writeMemory(imageLoadAddr, self.destAppFilename, self.bootDeviceMemId)
            self.printLog(cmdStr)
            if status != boot.status.kStatus_Success:
                return False
        else:
            pass
        self.invalidateStepButtonColor(uidef.kSecureBootSeqStep_FlashImage)
        return True

    def _getMcuDeviceBeeKeySel( self ):
        beeKeySel = self.readMcuDeviceFuseByBlhost(fusedef.kEfuseLocation_BeeKeySel, '', False)
        if beeKeySel != None:
            self.mcuDeviceBeeKey0Sel = ((beeKeySel & fusedef.kEfuseMask_BeeKey0Sel) >> fusedef.kEfuseShift_BeeKey0Sel)
            self.mcuDeviceBeeKey1Sel = ((beeKeySel & fusedef.kEfuseMask_BeeKey1Sel) >> fusedef.kEfuseShift_BeeKey1Sel)
        return beeKeySel

    def burnBeeKeySel( self ):
        setBeeKey0Sel = None
        setBeeKey1Sel = None
        if self.keyStorageRegion == uidef.kKeyStorageRegion_FixedOtpmkKey:
            otpmkKeyOpt, otpmkEncryptedRegionStart, otpmkEncryptedRegionLength = uivar.getAdvancedSettings(uidef.kAdvancedSettings_OtpmkKey)
            encryptedRegionCnt = (otpmkKeyOpt & 0x000F0000) >> 16
            # One PRDB means one BEE_KEY, no matter how many FAC regions it has
            if encryptedRegionCnt >= 0:
                setBeeKey0Sel = fusedef.kBeeKeySel_FromOtpmk
            #if encryptedRegionCnt > 1:
            #    setBeeKey1Sel = fusedef.kBeeKeySel_FromOtpmk
        elif self.keyStorageRegion == uidef.kKeyStorageRegion_FlexibleUserKeys:
            userKeyCtrlDict, userKeyCmdDict = uivar.getAdvancedSettings(uidef.kAdvancedSettings_UserKeys)
            if userKeyCtrlDict['engine_sel'] == uidef.kUserEngineSel_Engine0 or userKeyCtrlDict['engine_sel'] == uidef.kUserEngineSel_BothEngines:
                if userKeyCtrlDict['engine0_key_src'] == uidef.kUserKeySource_OTPMK:
                    setBeeKey0Sel = fusedef.kBeeKeySel_FromOtpmk
                elif userKeyCtrlDict['engine0_key_src'] == uidef.kUserKeySource_SW_GP2:
                    setBeeKey0Sel = fusedef.kBeeKeySel_FromSwGp2
                elif userKeyCtrlDict['engine0_key_src'] == uidef.kUserKeySource_GP4:
                    setBeeKey0Sel = fusedef.kBeeKeySel_FromGp4
                else:
                    pass
            if userKeyCtrlDict['engine_sel'] == uidef.kUserEngineSel_Engine1 or userKeyCtrlDict['engine_sel'] == uidef.kUserEngineSel_BothEngines:
                if userKeyCtrlDict['engine0_key_src'] == uidef.kUserKeySource_OTPMK:
                    setBeeKey1Sel = fusedef.kBeeKeySel_FromOtpmk
                elif userKeyCtrlDict['engine1_key_src'] == uidef.kUserKeySource_SW_GP2:
                    setBeeKey1Sel = fusedef.kBeeKeySel_FromSwGp2
                elif userKeyCtrlDict['engine1_key_src'] == uidef.kUserKeySource_GP4:
                    setBeeKey1Sel = fusedef.kBeeKeySel_FromGp4
                else:
                    pass
        else:
            pass
        getBeeKeySel = self._getMcuDeviceBeeKeySel()
        if getBeeKeySel != None:
            if setBeeKey0Sel != None:
                getBeeKeySel = getBeeKeySel | (setBeeKey0Sel << fusedef.kEfuseShift_BeeKey0Sel)
                if ((getBeeKeySel & fusedef.kEfuseMask_BeeKey0Sel) >> fusedef.kEfuseShift_BeeKey0Sel) != setBeeKey0Sel:
                    self.popupMsgBox('Fuse BOOT_CFG1[5:4] BEE_KEY0_SEL has been burned, it is program-once!')
                    return False
            if setBeeKey1Sel != None:
                getBeeKeySel = getBeeKeySel | (setBeeKey1Sel << fusedef.kEfuseShift_BeeKey1Sel)
                if ((getBeeKeySel & fusedef.kEfuseMask_BeeKey1Sel) >> fusedef.kEfuseShift_BeeKey1Sel) != setBeeKey1Sel:
                    self.popupMsgBox('Fuse BOOT_CFG1[7:6] BEE_KEY1_SEL has been burned, it is program-once!')
                    return False
            self.burnMcuDeviceFuseByBlhost(fusedef.kEfuseLocation_BeeKeySel, getBeeKeySel)
        return True

    def flashHabDekToGenerateKeyBlob ( self ):
        if os.path.isfile(self.habDekFilename) and self.habDekDataOffset != None:
            self._prepareForBootDeviceOperation()
            imageLen = os.path.getsize(self.destAppFilename)
            imageCopies = 0x1
            if self.bootDevice == uidef.kBootDevice_SemcNand:
                imageCopies = self.semcNandImageCopies
            else:
                pass
            # Construct KeyBlob Option
            #---------------------------------------------------------------------------
            # bit [31:28] tag, fixed to 0x0b
            # bit [27:24] type, 0 - Update KeyBlob context, 1 Program Keyblob to SPI NAND
            # bit [23:20] keyblob option block size, must equal to 3 if type =0,
            #             reserved if type = 1
            # bit [19:08] Reserved
            # bit [07:04] DEK size, 0-128bit 1-192bit 2-256 bit, only applicable if type=0
            # bit [03:00] Firmware Index, only applicable if type = 1
            # if type = 0, next words indicate the address that holds dek
            #              the 3rd word
            #----------------------------------------------------------------------------
            keyBlobContextOpt = 0xb0300000
            keyBlobDataOpt = 0xb1000000
            status, results, cmdStr = self.blhost.writeMemory(rundef.kRamFreeSpaceStart_LoadDekData, self.habDekFilename)
            self.printLog(cmdStr)
            if status != boot.status.kStatus_Success:
                return False
            status, results, cmdStr = self.blhost.fillMemory(rundef.kRamFreeSpaceStart_LoadKeyBlobContext, 0x4, keyBlobContextOpt)
            self.printLog(cmdStr)
            if status != boot.status.kStatus_Success:
                return False
            status, results, cmdStr = self.blhost.fillMemory(rundef.kRamFreeSpaceStart_LoadKeyBlobContext + 4, 0x4, rundef.kRamFreeSpaceStart_LoadDekData)
            self.printLog(cmdStr)
            if status != boot.status.kStatus_Success:
                return False
            status, results, cmdStr = self.blhost.fillMemory(rundef.kRamFreeSpaceStart_LoadKeyBlobContext + 8, 0x4, self.habDekDataOffset)
            self.printLog(cmdStr)
            if status != boot.status.kStatus_Success:
                return False
            status, results, cmdStr = self.blhost.configureMemory(self.bootDeviceMemId, rundef.kRamFreeSpaceStart_LoadKeyBlobContext)
            self.printLog(cmdStr)
            if status != boot.status.kStatus_Success:
                return False
            for i in range(imageCopies):
                ramFreeSpace = rundef.kRamFreeSpaceStart_LoadKeyBlobData + (rundef.kRamFreeSpaceStep_LoadKeyBlobData * i)
                status, results, cmdStr = self.blhost.fillMemory(ramFreeSpace, 0x4, keyBlobDataOpt + i)
                self.printLog(cmdStr)
                if status != boot.status.kStatus_Success:
                    return False
                ########################################################################
                # Flashloader will not erase keyblob region automatically, so we need to handle it here manually
                imageLoadAddr = 0x0
                if self.bootDevice == uidef.kBootDevice_SemcNand:
                    semcNandOpt, semcNandFcbOpt, imageInfo = uivar.getBootDeviceConfiguration(self.bootDevice)
                    imageLoadAddr = self.bootDeviceMemBase + (imageInfo[i] >> 16) * self.semcNandBlockSize
                elif self.bootDevice == uidef.kBootDevice_FlexspiNor or self.bootDevice == uidef.kBootDevice_LpspiNor:
                    imageLoadAddr = self.bootDeviceMemBase
                else:
                    pass
                alignedErasedSize = misc.align_up(imageLen, self.comMemEraseUnit)
                needToBeErasedSize = misc.align_up(self.habDekDataOffset + memdef.kMemBlockSize_KeyBlob, self.comMemEraseUnit)
                if alignedErasedSize < needToBeErasedSize:
                    memEraseLen = needToBeErasedSize - alignedErasedSize
                    alignedMemEraseAddr = imageLoadAddr + alignedErasedSize
                    status, results, cmdStr = self.blhost.flashEraseRegion(alignedMemEraseAddr, memEraseLen, self.bootDeviceMemId)
                    self.printLog(cmdStr)
                    if status != boot.status.kStatus_Success:
                        return False
                ########################################################################
                status, results, cmdStr = self.blhost.configureMemory(self.bootDeviceMemId, ramFreeSpace)
                self.printLog(cmdStr)
                if status != boot.status.kStatus_Success:
                    return False
            if self.bootDevice == uidef.kBootDevice_FlexspiNor:
                if not self._programFlexspiNorConfigBlock():
                    return False
            self.showImageLayout(u"../img/image_signed_hab_encrypted.png")
            self.invalidateStepButtonColor(uidef.kSecureBootSeqStep_ProgDek)
            return True
        else:
            self.popupMsgBox('Dek file hasn\'t been generated!')
            return False

    def enableHab( self ):
        if self.mcuDeviceHabStatus != fusedef.kHabStatus_Closed0 and \
           self.mcuDeviceHabStatus != fusedef.kHabStatus_Closed1:
            secConfig1 = self.readMcuDeviceFuseByBlhost(fusedef.kEfuseLocation_SecConfig1, '', False)
            if secConfig1 != None:
                secConfig1 = secConfig1 | fusedef.kEfuseMask_SecConfig1
                self.burnMcuDeviceFuseByBlhost(fusedef.kEfuseLocation_SecConfig1, secConfig1)

    def resetMcuDevice( self ):
        status, results, cmdStr = self.blhost.reset()
        self.printLog(cmdStr)
        return (status == boot.status.kStatus_Success)
