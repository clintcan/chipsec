#!/usr/bin/python
#CHIPSEC: Platform Security Assessment Framework
#Copyright (c) 2010-2019, Intel Corporation
# 
#This program is free software; you can redistribute it and/or
#modify it under the terms of the GNU General Public License
#as published by the Free Software Foundation; Version 2.
#
#This program is distributed in the hope that it will be useful,
#but WITHOUT ANY WARRANTY; without even the implied warranty of
#MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#GNU General Public License for more details.
#
#You should have received a copy of the GNU General Public License
#along with this program; if not, write to the Free Software
#Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301, USA.
#
#Contact information:
#chipsec@intel.com
#



# -------------------------------------------------------------------------------
#
# CHIPSEC: Platform Hardware Security Assessment Framework
# (c) 2010-2018 Intel Corporation
#
# -------------------------------------------------------------------------------

"""
Abstracts support for various OS/environments, wrapper around platform specific code that invokes kernel driver
"""

import os
import fnmatch
import re
import errno
import shutil
import traceback
import sys

import chipsec.file
from chipsec.logger import *

_importlib = True
try:
    import importlib

except ImportError:
    _importlib = False


ZIP_HELPER_RE = re.compile("^chipsec\/helper\/\w+\/\w+\.pyc$", re.IGNORECASE)
def f_mod_zip(x):
    return ( x.find('__init__') == -1 and ZIP_HELPER_RE.match(x) )
def map_modname_zip(x):
    return (x.rpartition('.')[0]).replace('/','.')

class OsHelperError (RuntimeError):
    def __init__(self,msg,errorcode):
        super(OsHelperError,self).__init__(msg)
        self.errorcode = errorcode

class HWAccessViolationError (OsHelperError):
    pass

class UnimplementedAPIError (OsHelperError):
    def __init__(self,api_name):
        super(UnimplementedAPIError,self).__init__("'%s' is not implemented" % api_name, 0)

class UnimplementedNativeAPIError (UnimplementedAPIError):
    def __init__(self,api_name):
        super(UnimplementedNativeAPIError,self).__init__(api_name)

def get_tools_path():
    return os.path.normpath( os.path.join(chipsec.file.get_main_dir(), chipsec.file.TOOLS_DIR) )

# Base class for the helpers
class Helper(object):
    class __metaclass__(type):
        def __init__(cls, name, bases, attrs):
            if not hasattr(cls, 'registry'):
                cls.registry = []
            else:
                cls.registry.append((name, cls))

    def __init__(self):
        self.driver_loaded = False

    def use_native_api(self):
        return (not self.driver_loaded)

import chipsec.helper.helpers

## OS Helper
#
# Abstracts support for various OS/environments, wrapper around platform specific code that invokes kernel driver
class OsHelper:
    def __init__(self):
        self.helper = None
        self.loadHelpers()
        self.filehelper = None
        #print "Operating System: %s %s %s %s" % (self.os_system, self.os_release, self.os_version, self.os_machine)
        #print self.os_uname
        if(not self.helper):
            import platform
            os_system  = platform.system()
            #raise OsHelperError("Unsupported platform '%s'" % os_system,errno.ENODEV)
            raise OsHelperError( "Could not load helper for '%s' environment (unsupported environment?)" % os_system, errno.ENODEV )
        else:
            self.os_system  = self.helper.os_system
            self.os_release = self.helper.os_release
            self.os_version = self.helper.os_version
            self.os_machine = self.helper.os_machine

    def loadHelpers(self):
        for name, cls in Helper.registry:
            try:
                self.helper = cls()
                break
            except OsHelperError:
                raise
            except:
                pass

    def start(self, start_driver, driver_exists=False, to_file=None):
        if not to_file is None:
            from chipsec.helper.file.helper import FileCmds
            self.filehelper = FileCmds(to_file)
        try:
            if not self.helper.create( start_driver ):
                raise OsHelperError("failed to create OS helper")
            if not self.helper.start( start_driver, driver_exists ):
                raise OsHelperError("failed to start OS helper")
        except (None,Exception) , msg:
            if logger().VERBOSE: logger().log_bad(traceback.format_exc())
            error_no = errno.ENXIO
            if hasattr(msg,'errorcode'):
                error_no = msg.errorcode
            raise OsHelperError("Could not start the OS Helper, are you running as Admin/root?\n           Message: \"%s\"" % msg,error_no)

    def stop( self, start_driver ):
        if not self.filehelper is None:
            self.filehelper.Save()
        if not self.helper.stop( start_driver ):
            logger().warn("failed to stop OS helper") 
        else:
            if not self.helper.delete( start_driver ):
                logger().warn("failed to delete OS helper")

    #
    # use_native_api
    # Defines if CHIPSEC should use its own API or native environment/OS API
    #
    # Returns:
    #   True  if CHIPSEC needs to use native OS/environment API
    #   False if CHIPSEC needs to use its own (OS agnostic) implementation of helper API
    #
    # Currently, CHIPSEC will use native API only if CHIPSEC driver wasn't loaded
    # (e.g. when --no_driver command-line option is specified).
    # In future, it can can more conditions
    # 
    def use_native_api(self):
        return self.helper.use_native_api()

    def is_dal( self ):
        return ('itpii' in sys.modules)
    def is_efi( self ):
        return self.os_system.lower().startswith('efi') or self.os_system.lower().startswith('uefi')
    def is_linux( self ):
        return ('linux' == self.os_system.lower())
    def is_windows( self ):
        return ('windows' == self.os_system.lower())
    def is_win8_or_greater( self ):
        win8_or_greater = self.is_windows() and ( self.os_release.startswith('8') or ('2008Server' in self.os_release) or ('2012Server' in self.os_release) )
        return win8_or_greater
    def is_macos( self ):
        return ('darwin' == self.os_system.lower())


    #################################################################################################
    # Actual OS helper functionality accessible to HAL components

    #
    # Read/Write PCI configuration registers via legacy CF8/CFC ports
    #
    def read_pci_reg( self, bus, device, function, address, size ):
        """Read PCI configuration registers via legacy CF8/CFC ports"""
        if ( 0 != (address & (size - 1)) ):
            logger().warn( "Config register address is not naturally aligned" )

        if self.use_native_api() and hasattr(self.helper, 'native_read_pci_reg'):
            ret = self.helper.native_read_pci_reg( bus, device, function, address, size )
        else:
            ret = self.helper.read_pci_reg( bus, device, function, address, size )
        if not self.filehelper is None:
            self.filehelper.AddElement("read_pci_reg",(bus,device,function,address,size),ret)
        return ret

    def write_pci_reg( self, bus, device, function, address, value, size ):
        """Write PCI configuration registers via legacy CF8/CFC ports"""
        if ( 0 != (address & (size - 1)) ):
            logger().warn( "Config register address is not naturally aligned" )

        if self.use_native_api() and hasattr(self.helper, 'native_write_pci_reg'):
            ret = self.helper.native_write_pci_reg( bus, device, function, address, value, size )
        else:
            ret = self.helper.write_pci_reg( bus, device, function, address, value, size ) 
        if not self.filehelper is None:
            self.filehelper.AddElement("write_pci_reg",(bus,device,function,address,size),ret)
        return ret

    #
    # read/write mmio
    #
    def read_mmio_reg( self, bar_base, size, offset=0, bar_size=None ):
        if self.use_native_api() and hasattr(self.helper, 'native_read_mmio_reg'):
            ret = self.helper.native_read_mmio_reg( bar_base, bar_size, offset, size )
        else:
            ret = self.helper.read_mmio_reg( bar_base+offset, size )
        if not self.filehelper is None:
            self.filehelper.AddElement("read_mmio_reg",(phys_address,size),ret)
        return ret
        
    def write_mmio_reg( self, bar_base, size, value, offset=0, bar_size=None ):
        if self.use_native_api() and hasattr(self.helper, 'native_write_mmio_reg'):
            ret = self.helper.native_write_mmio_reg( bar_base, bar_size, offset, size, value )
        else:
            ret = self.helper.write_mmio_reg(bar_base+offset, size, value )
        if not self.filehelper is None:
            self.filehelper.AddElement("write_mmio_reg",(phys_address, size, value),ret)
        return ret
        
    #
    # physical_address is 64 bit integer
    #
    def read_physical_mem( self, phys_address, length ):
        #return self.helper.read_phys_mem( (phys_address>>32)&0xFFFFFFFF, phys_address&0xFFFFFFFF, length )
        if self.use_native_api() and hasattr(self.helper, 'native_read_phys_mem'):
            ret = self.helper.native_read_phys_mem( (phys_address>>32)&0xFFFFFFFF, phys_address&0xFFFFFFFF, length )
        else:
            ret = self.helper.read_phys_mem( (phys_address>>32)&0xFFFFFFFF, phys_address&0xFFFFFFFF, length )
        if not self.filehelper is None:
            self.filehelper.AddElement("read_physical_mem",((phys_address>>32)&0xFFFFFFFF, phys_address&0xFFFFFFFF,length),ret)
        return ret

    def write_physical_mem( self, phys_address, length, buf ):
        if self.use_native_api() and hasattr(self.helper, 'native_write_phys_mem'):
            ret = self.helper.native_write_phys_mem( (phys_address>>32)&0xFFFFFFFF, phys_address&0xFFFFFFFF, length, buf )
        else:
            ret = self.helper.write_phys_mem( (phys_address>>32)&0xFFFFFFFF, phys_address&0xFFFFFFFF, length, buf )
        if not self.filehelper is None:
            self.filehelper.AddElement("write_physical_mem",((phys_address>>32)&0xFFFFFFFF, phys_address&0xFFFFFFFF,length,buf),ret)
        return ret

    def alloc_physical_mem( self, length, max_phys_address ):
        if self.use_native_api() and hasattr(self.helper, 'native_alloc_phys_mem'):
            ret = self.helper.native_alloc_phys_mem( length, max_phys_address )
        else:
            ret = self.helper.alloc_phys_mem( length, max_phys_address )
        if not self.filehelper is None:
            self.filehelper.AddElement("alloc_physical_mem",(length,max_phys_address),ret)
        return ret

    def free_physical_mem(self, physical_address):
        if self.use_native_api() and hasattr(self.helper, 'native_free_phys_mem'):
            ret = self.helper.native_free_phys_mem(physical_address)
        else:
            ret = self.helper.free_phys_mem(physical_address)
        if not self.filehelper is None:
            self.filehelper.AddElement("free_physical_mem",(phys_address),ret)
        return ret

    def va2pa( self, va ):
        if self.use_native_api() and hasattr(self.helper, 'native_va2pa'):
            ret = self.helper.native_va2pa( va )
        else:
            ret = self.helper.va2pa( va )
        if not self.filehelper is None:
            self.filehelper.AddElement("va2pa",(va),ret)
        return ret

    def map_io_space(self, physical_address, length, cache_type):
        try:
            if self.use_native_api() and hasattr(self.helper, 'native_map_io_space'):
                ret = self.helper.native_map_io_space(physical_address, length, cache_type)
            elif hasattr(self.helper, 'map_io_space'):
                ret = self.helper.map_io_space(physical_address, length, cache_type)
            if not self.filehelper is None:
                self.filehelper.AddElement("map_io_space",(physical_address, length, cache_type),ret)
            return ret
        except NotImplementedError:
            pass
        raise UnimplementedAPIError('map_io_space')

    #
    # Read/Write I/O port
    #
    def read_io_port( self, io_port, size ):
        if self.use_native_api() and hasattr(self.helper, 'native_read_io_port'):
            ret = self.helper.native_read_io_port( io_port, size )
        else:
            ret = self.helper.read_io_port( io_port, size )
        if not self.filehelper is None:
            self.filehelper.AddElement("read_io_port",(io_port,size),ret)
        return ret

    def write_io_port( self, io_port, value, size ):
        if self.use_native_api() and hasattr(self.helper, 'native_write_io_port'):
            ret = self.helper.native_write_io_port( io_port, value, size )
        else:
            ret = self.helper.write_io_port( io_port, value, size )
        if not self.filehelper is None:
            self.filehelper.AddElement("write_io_port",(io_port,value,size),ret)
        return ret

    #
    # Read/Write CR registers
    #
    def read_cr(self, cpu_thread_id, cr_number):
        if self.use_native_api() and hasattr(self.helper, 'native_read_cr'):
            ret = self.helper.native_read_cr( cpu_thread_id, cr_number )
        else:
            ret = self.helper.read_cr( cpu_thread_id, cr_number )
        if not self.filehelper is None:
            self.filehelper.AddElement("read_cr",(cpu_thread_id, cr_number),ret)
        return ret

    def write_cr(self, cpu_thread_id, cr_number, value):
        if self.use_native_api() and hasattr(self.helper, 'native_write_cr'):
            ret = self.helper.native_write_cr( cpu_thread_id, cr_number, value )
        else:
            ret = self.helper.write_cr( cpu_thread_id, cr_number, value )
        if not self.filehelper is None:
            self.filehelper.AddElement("write_cr",(cpu_thread_id, cr_number,value),ret)
        return ret

    #
    # Read/Write MSR on a specific CPU thread
    #
    def read_msr( self, cpu_thread_id, msr_addr ):
        if self.use_native_api() and hasattr(self.helper, 'native_read_msr'):
            ret = self.helper.native_read_msr( cpu_thread_id, msr_addr )
        else:
            ret = self.helper.read_msr( cpu_thread_id, msr_addr )
        if not self.filehelper is None:
            self.filehelper.AddElement("read_msr",(cpu_thread_id, msr_addr),ret)
        return ret

    def write_msr( self, cpu_thread_id, msr_addr, eax, edx ):
        if self.use_native_api() and hasattr(self.helper, 'native_write_msr'):
            ret = self.helper.native_write_msr( cpu_thread_id, msr_addr, eax, edx )
        else:
            ret = self.helper.write_msr( cpu_thread_id, msr_addr, eax, edx )
        if not self.filehelper is None:
            self.filehelper.AddElement("write_msr",(cpu_thread_id, msr_addr, eax, edx),ret)
        return ret

    #
    # Load CPU microcode update on a specific CPU thread
    #
    def load_ucode_update( self, cpu_thread_id, ucode_update_buf ):
        if self.use_native_api() and hasattr(self.helper, 'native_load_ucode_update'):
            ret = self.helper.native_load_ucode_update( cpu_thread_id, ucode_update_buf )
        else:
            ret = self.helper.load_ucode_update( cpu_thread_id, ucode_update_buf )
        if not self.filehelper is None:
            self.filehelper.AddElement("load_ucode_update",(cpu_thread_id, ucode_update_buf),ret)
        return ret

    #
    # Read IDTR/GDTR/LDTR on a specific CPU thread
    #
    def get_descriptor_table( self, cpu_thread_id, desc_table_code ):
        if self.use_native_api() and hasattr(self.helper, 'native_get_descriptor_table'):
            ret = self.helper.native_get_descriptor_table( cpu_thread_id, desc_table_code )
        else:
            ret = self.helper.get_descriptor_table( cpu_thread_id, desc_table_code )
        if not self.filehelper is None:
            self.filehelper.AddElement("get_descriptor_table",(cpu_thread_id, desc_table_code),ret)
        return ret

    #
    # EFI Variable API
    #
    def EFI_supported(self):
        ret = self.helper.EFI_supported()
        if not self.filehelper is None:
            self.filehelper.AddElement("EFI_supported",(),ret)
        return ret

    def get_EFI_variable( self, name, guid ):
        if self.use_native_api() and hasattr(self.helper, 'native_get_EFI_variable'):
            ret = self.helper.native_get_EFI_variable( name, guid )
        else:
            ret = self.helper.get_EFI_variable( name, guid )
        if not self.filehelper is None:
            self.filehelper.AddElement("get_EFI_variable",(name, guid),ret)
        return ret

    def set_EFI_variable( self, name, guid, data, datasize=None, attrs=None ):
        if self.use_native_api() and hasattr(self.helper, 'native_set_EFI_variable'):
            ret = self.helper.native_set_EFI_variable( name, guid, data, datasize, attrs )
        else:
            ret = self.helper.set_EFI_variable( name, guid, data, datasize, attrs )
        if not self.filehelper is None:
            self.filehelper.AddElement("set_EFI_variable",(name, guid, data, datasize, attrs),ret)
        return ret

    def delete_EFI_variable( self, name, guid ):
        if self.use_native_api() and hasattr(self.helper, 'native_delete_EFI_variable'):
            ret = self.helper.native_delete_EFI_variable( name, guid )
        else:
            ret = self.helper.delete_EFI_variable( name, guid )
        if not self.filehelper is None:
            self.filehelper.AddElement("delete_EFI_variable",(name, guid),ret)            
        return ret

    def list_EFI_variables( self ):
        if self.use_native_api() and hasattr(self.helper, 'native_list_EFI_variables'):
            ret = self.helper.native_list_EFI_variables()
        else:
            ret = self.helper.list_EFI_variables()
        if not self.filehelper is None:
            self.filehelper.AddElement("list_EFI_variables",(),ret)
        return ret
    
    #
    # ACPI
    #
    def get_ACPI_SDT(self):
        ret = self.helper.get_ACPI_SDT()
        if not self.filehelper is None:
            self.filehelper.AddElement("get_ACPI_SDT",(),ret)
        return ret

    def get_ACPI_table( self, table_name ):
        #return self.helper.get_ACPI_table( table_name )
        if self.use_native_api() and hasattr(self.helper, 'native_get_ACPI_table'):
            ret = self.helper.native_get_ACPI_table( table_name )
        else:
            ret = self.helper.get_ACPI_table( table_name )
        if not self.filehelper is None:
            self.filehelper.AddElement("get_ACPI_table",(table_name),ret)
        return ret
        
   
    #
    # CPUID
    #
    def cpuid( self, eax, ecx ):
        if self.use_native_api() and hasattr(self.helper, 'native_cpuid'):
            ret = self.helper.native_cpuid( eax, ecx )
        else:
            ret = self.helper.cpuid( eax, ecx )
        if not self.filehelper is None:
            self.filehelper.AddElement("cpuid",(eax, ecx),ret)
        return ret
        
    #
    # IOSF Message Bus access
    #

    def msgbus_send_read_message( self, mcr, mcrx ):
        if self.use_native_api() and hasattr(self.helper, 'native_msgbus_send_read_message'):
            ret = self.helper.native_msgbus_send_read_message( mcr, mcrx )
        else:
            ret = self.helper.msgbus_send_read_message( mcr, mcrx )
        if not self.filehelper is None:
            self.filehelper.AddElement("msgbus_send_read_message",(mcr, mcrx),ret)
        return ret

    def msgbus_send_write_message( self, mcr, mcrx, mdr ):
        if self.use_native_api() and hasattr(self.helper, 'native_msgbus_send_write_message'):
            ret = self.helper.native_msgbus_send_write_message( mcr, mcrx, mdr )
        else:
            ret = self.helper.msgbus_send_write_message( mcr, mcrx, mdr )
        if not self.filehelper is None:
            self.filehelper.AddElement("msgbus_send_write_message",(mcr, mcrx, mdr),ret)
        return ret

    def msgbus_send_message( self, mcr, mcrx, mdr ):
        if self.use_native_api() and hasattr(self.helper, 'native_msgbus_send_message'):
            ret = self.helper.native_msgbus_send_message( mcr, mcrx, mdr )
        else:
            ret = self.helper.msgbus_send_message( mcr, mcrx, mdr )
        if not self.filehelper is None:
            self.filehelper.AddElement("msgbus_send_message",(mcr, mcrx, mdr),ret)
        return ret

    #
    # Affinity
    #
    def get_affinity( self ):
        if self.use_native_api() and hasattr(self.helper, 'native_get_affinity'):
            ret = self.helper.native_get_affinity()
        else:
            ret = self.helper.get_affinity()
        if not self.filehelper is None:
            self.filehelper.AddElement("get_affinity",(),ret)
        return ret
        
    def set_affinity( self, value ):
        if self.use_native_api() and hasattr(self.helper, 'native_set_affinity'):
            ret = self.helper.native_set_affinity( value )
        else:
            ret = self.helper.get_affinity()
        if not self.filehelper is None:
            self.filehelper.AddElement("set_affinity",(value),ret)
        return ret
        
    #
    # Logical CPU count
    #
    def get_threads_count( self ):
        if self.use_native_api() and hasattr(self.helper, 'native_get_threads_count'):
            ret = self.helper.native_get_threads_count()
        else:
            ret = self.helper.get_threads_count()
        if not self.filehelper is None:
            self.filehelper.AddElement("get_threads_count",(),ret)
        return ret

    #
    # Send SW SMI
    #
    def send_sw_smi( self, cpu_thread_id, SMI_code_data, _rax, _rbx, _rcx, _rdx, _rsi, _rdi ):
        if self.use_native_api() and hasattr(self.helper, 'native_send_sw_smi'):
            ret = self.helper.native_send_sw_smi( cpu_thread_id, SMI_code_data, _rax, _rbx, _rcx, _rdx, _rsi, _rdi )
        else:
            ret = self.helper.send_sw_smi( cpu_thread_id, SMI_code_data, _rax, _rbx, _rcx, _rdx, _rsi, _rdi )
        if not self.filehelper is None:
            self.filehelper.AddElement("send_sw_smi",(cpu_thread_id, SMI_code_data, _rax, _rbx, _rcx, _rdx, _rsi, _rdi),ret)
        return ret

    #
    # Hypercall
    #
    def hypercall( self, rcx=0, rdx=0, r8=0, r9=0, r10=0, r11=0, rax=0, rbx=0, rdi=0, rsi=0, xmm_buffer=0 ):
        if self.use_native_api() and hasattr(self.helper, 'native_hypercall'):
            ret = self.helper.native_hypercall( rcx, rdx, r8, r9, r10, r11, rax, rbx, rdi, rsi, xmm_buffer )
        else:
            ret = self.helper.hypercall( rcx, rdx, r8, r9, r10, r11, rax, rbx, rdi, rsi, xmm_buffer )
        if not self.filehelper is None:
            self.filehelper.AddElement("hypercall",(rcx, rdx, r8, r9, r10, r11, rax, rbx, rdi, rsi, xmm_buffer),ret)
        return ret


    #
    # File system
    #
    def getcwd( self ):
        ret = self.helper.getcwd()
        if not self.filehelper is None:
            self.filehelper.AddElement("getcwd",(),ret)
        return ret
    #
    # Decompress binary with OS specific tools
    #
    def decompress_file( self, CompressedFileName, OutputFileName, CompressionType ):
        ret = self.helper.decompress_file( CompressedFileName, OutputFileName, CompressionType )
        if not self.filehelper is None:
            self.filehelper.AddElement("decompress_file",(CompressedFileName, OutputFileName, CompressionType),ret)
        return ret

    #
    # Compress binary with OS specific tools
    #
    def compress_file( self, FileName, OutputFileName, CompressionType ):
        import subprocess
        if (CompressionType == 0): # not compressed
          shutil.copyfile(FileName, OutputFileName)
        else:
          exe = self.get_compression_tool_path( CompressionType )
          if exe is None: return None 
          try:
            subprocess.call( [ exe, "-e", "-o", OutputFileName, FileName ], stdout=open(os.devnull, 'wb') )
          except BaseException, msg:
            logger().error( str(msg) )
            if logger().DEBUG: logger().log_bad( traceback.format_exc() )
            return None

        ret = chipsec.file.read_file( OutputFileName )
        if not self.filehelper is None:
            self.filehelper.AddElement("compress_file",(FileName, OutputFileName, CompressionType),ret)
        return ret

_helper = None

def helper():
    global _helper
    if _helper == None:
        try:
            _helper  = OsHelper()
        except BaseException, msg:
            logger().error( str(msg) )
            if logger().DEBUG: logger().log_bad(traceback.format_exc())
            raise
    return _helper
