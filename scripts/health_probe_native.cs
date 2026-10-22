// Windows PowerShell 5.1: own the probe and every descendant before it can run.
using System;
using System.ComponentModel;
using System.Diagnostics;
using System.IO;
using System.Runtime.InteropServices;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using Microsoft.Win32.SafeHandles;

public sealed class MarketFlowOwnedHealthProbe : IDisposable
{
    private IntPtr job;
    private IntPtr process;
    private readonly StreamReader stdout;
    private readonly StreamReader stderr;
    public readonly Task<string> Output;
    private readonly Task<string> errorDrain;
    public readonly int Id;

    private MarketFlowOwnedHealthProbe(IntPtr ownedJob, IntPtr ownedProcess, int id,
                                      StreamReader output, StreamReader errors)
    {
        job = ownedJob;
        process = ownedProcess;
        Id = id;
        stdout = output;
        stderr = errors;
        Output = Task.Run(() => Drain(stdout, 4096));
        // Drain, but never retain or return arbitrary private stderr.
        errorDrain = Task.Run(() => Drain(stderr, 0));
    }

    private static string Drain(StreamReader stream, int limit)
    {
        var text = new StringBuilder();
        var buffer = new char[512];
        bool tooLarge = false;
        int count;
        while ((count = stream.Read(buffer, 0, buffer.Length)) > 0)
        {
            if (limit > 0 && !tooLarge)
            {
                if (text.Length + count > limit) { tooLarge = true; text.Clear(); }
                else { text.Append(buffer, 0, count); }
            }
        }
        return tooLarge || limit == 0 ? null : text.ToString();
    }

    public static MarketFlowOwnedHealthProbe Start(string executable, string arguments)
    {
        IntPtr ownedJob = IntPtr.Zero, outputRead = IntPtr.Zero, outputWrite = IntPtr.Zero;
        IntPtr errorRead = IntPtr.Zero, errorWrite = IntPtr.Zero;
        IntPtr attributeList = IntPtr.Zero, inheritedHandles = IntPtr.Zero;
        bool attributesInitialized = false;
        var pi = new PROCESS_INFORMATION();
        StreamReader output = null, errors = null;
        try
        {
            ownedJob = CreateJobObject(IntPtr.Zero, null);
            Check(ownedJob != IntPtr.Zero);
            Check(SetHandleInformation(ownedJob, 1, 0));
            var limits = new JOBOBJECT_EXTENDED_LIMIT_INFORMATION();
            limits.BasicLimitInformation.LimitFlags = 0x00002000; // KILL_ON_JOB_CLOSE
            Check(SetInformationJobObject(ownedJob, 9, ref limits, (uint)Marshal.SizeOf(limits)));
            var security = new SECURITY_ATTRIBUTES();
            security.Length = Marshal.SizeOf(security);
            security.InheritHandle = true;
            Check(CreatePipe(out outputRead, out outputWrite, ref security, 0));
            Check(CreatePipe(out errorRead, out errorWrite, ref security, 0));
            Check(SetHandleInformation(outputRead, 1, 0));
            Check(SetHandleInformation(errorRead, 1, 0));
            var startup = new STARTUPINFOEX();
            startup.Startup.Size = Marshal.SizeOf(startup);
            startup.Startup.Flags = 0x00000100; // STARTF_USESTDHANDLES
            startup.Startup.StandardOutput = outputWrite;
            startup.Startup.StandardError = errorWrite;
            // Inherit only our two pipe writers, never unrelated handles or
            // the outer PowerShell capture pipes. The job is uninheritable.
            IntPtr attributeBytes = IntPtr.Zero;
            InitializeProcThreadAttributeList(IntPtr.Zero, 1, 0, ref attributeBytes);
            if (attributeBytes.ToInt64() <= 0 || attributeBytes.ToInt64() > 65536)
                throw new InvalidOperationException("Invalid process attribute size");
            attributeList = Marshal.AllocHGlobal(attributeBytes);
            Check(InitializeProcThreadAttributeList(attributeList, 1, 0, ref attributeBytes));
            attributesInitialized = true;
            inheritedHandles = Marshal.AllocHGlobal(2 * IntPtr.Size);
            Marshal.WriteIntPtr(inheritedHandles, 0, outputWrite);
            Marshal.WriteIntPtr(inheritedHandles, IntPtr.Size, errorWrite);
            Check(UpdateProcThreadAttribute(attributeList, 0, new IntPtr(0x00020002),
                                           inheritedHandles, new IntPtr(2 * IntPtr.Size),
                                           IntPtr.Zero, IntPtr.Zero));
            startup.AttributeList = attributeList;
            // No stdin is needed by the read-only, noninteractive probe.
            var command = new StringBuilder("\"" + executable + "\" " + arguments);
            Check(CreateProcess(executable, command, IntPtr.Zero, IntPtr.Zero, true,
                                0x08080004, IntPtr.Zero, null, ref startup, out pi));
            // NO_WINDOW | EXTENDED_STARTUPINFO | SUSPENDED; no BREAKAWAY.
            Close(ref outputWrite);
            Close(ref errorWrite);
            Check(AssignProcessToJobObject(ownedJob, pi.Process));
            output = Reader(ref outputRead);
            errors = Reader(ref errorRead);
            var probe = new MarketFlowOwnedHealthProbe(ownedJob, pi.Process, (int)pi.ProcessId, output, errors);
            Check(ResumeThread(pi.Thread) != 0xffffffff);
            ownedJob = IntPtr.Zero;
            pi.Process = IntPtr.Zero;
            output = null;
            errors = null;
            return probe;
        }
        catch
        {
            // Assignment/resume failure must never run an unowned child. The
            // process handle still identifies exactly our created process.
            if (ownedJob != IntPtr.Zero) { TerminateJobObject(ownedJob, 1); }
            if (pi.Process != IntPtr.Zero)
            {
                TerminateProcess(pi.Process, 1);
                WaitForSingleObject(pi.Process, 300);
            }
            throw;
        }
        finally
        {
            if (attributesInitialized) { DeleteProcThreadAttributeList(attributeList); }
            if (attributeList != IntPtr.Zero) { Marshal.FreeHGlobal(attributeList); }
            if (inheritedHandles != IntPtr.Zero) { Marshal.FreeHGlobal(inheritedHandles); }
            Close(ref pi.Thread);
            Close(ref pi.Process);
            Close(ref ownedJob);
            Close(ref outputRead);
            Close(ref outputWrite);
            Close(ref errorRead);
            Close(ref errorWrite);
            if (output != null) { output.Dispose(); }
            if (errors != null) { errors.Dispose(); }
        }
    }

    private static StreamReader Reader(ref IntPtr handle)
    {
        var safe = new SafeFileHandle(handle, true);
        handle = IntPtr.Zero;
        try { return new StreamReader(new FileStream(safe, FileAccess.Read, 512, false), Encoding.UTF8); }
        catch { safe.Dispose(); throw; }
    }

    public bool WaitForExit(int milliseconds)
    {
        uint result = WaitForSingleObject(process, (uint)milliseconds);
        if (result == 0xffffffff) { throw new Win32Exception(); }
        return result == 0;
    }

    public int ExitCode
    {
        get { uint code; Check(GetExitCodeProcess(process, out code)); return unchecked((int)code); }
    }

    public bool Stop(int milliseconds)
    {
        if (job == IntPtr.Zero) { return true; }
        bool terminated = TerminateJobObject(job, 1);
        var clock = Stopwatch.StartNew();
        while (true)
        {
            JOBOBJECT_BASIC_ACCOUNTING_INFORMATION info;
            uint length;
            if (!QueryInformationJobObject(job, 1, out info, (uint)Marshal.SizeOf(typeof(JOBOBJECT_BASIC_ACCOUNTING_INFORMATION)), out length)) { return false; }
            if (info.ActiveProcesses == 0) { return terminated; }
            if (clock.ElapsedMilliseconds >= milliseconds) { return false; }
            Thread.Sleep(5);
        }
    }

    public void Dispose()
    {
        // Closing the uninherited job is a final kill guarantee even if Stop
        // reported failure, or if the immediate forwarding parent exited.
        Close(ref job);
        Close(ref process);
        try { stdout.Dispose(); } catch { }
        try { stderr.Dispose(); } catch { }
    }

    private static void Check(bool result) { if (!result) { throw new Win32Exception(); } }
    private static void Close(ref IntPtr handle)
    {
        if (handle != IntPtr.Zero) { CloseHandle(handle); handle = IntPtr.Zero; }
    }

    [StructLayout(LayoutKind.Sequential)] private struct SECURITY_ATTRIBUTES
    { public int Length; public IntPtr Descriptor; [MarshalAs(UnmanagedType.Bool)] public bool InheritHandle; }
    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)] private struct STARTUPINFO
    {
        public int Size; public string Reserved, Desktop, Title;
        public int X, Y, XSize, YSize, XCountChars, YCountChars, FillAttribute, Flags;
        public short ShowWindow, ReservedSize; public IntPtr ReservedPointer, StandardInput, StandardOutput, StandardError;
    }
    [StructLayout(LayoutKind.Sequential)] private struct PROCESS_INFORMATION
    { public IntPtr Process, Thread; public uint ProcessId, ThreadId; }
    [StructLayout(LayoutKind.Sequential)] private struct STARTUPINFOEX
    { public STARTUPINFO Startup; public IntPtr AttributeList; }
    [StructLayout(LayoutKind.Sequential)] private struct JOBOBJECT_BASIC_LIMIT_INFORMATION
    {
        public long ProcessTime, JobTime; public uint LimitFlags;
        public UIntPtr MinimumWorkingSetSize, MaximumWorkingSetSize;
        public uint ActiveProcessLimit; public UIntPtr Affinity; public uint PriorityClass, SchedulingClass;
    }
    [StructLayout(LayoutKind.Sequential)] private struct IO_COUNTERS
    { public ulong ReadOperations, WriteOperations, OtherOperations, ReadBytes, WriteBytes, OtherBytes; }
    [StructLayout(LayoutKind.Sequential)] private struct JOBOBJECT_EXTENDED_LIMIT_INFORMATION
    {
        public JOBOBJECT_BASIC_LIMIT_INFORMATION BasicLimitInformation; public IO_COUNTERS IoInfo;
        public UIntPtr ProcessMemoryLimit, JobMemoryLimit, PeakProcessMemoryUsed, PeakJobMemoryUsed;
    }
    [StructLayout(LayoutKind.Sequential)] private struct JOBOBJECT_BASIC_ACCOUNTING_INFORMATION
    {
        public long UserTime, KernelTime, PeriodUserTime, PeriodKernelTime;
        public uint PageFaults, TotalProcesses, ActiveProcesses, TerminatedProcesses;
    }
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern IntPtr CreateJobObject(IntPtr attributes, string name);
    [DllImport("kernel32.dll", SetLastError = true)] [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool SetInformationJobObject(IntPtr job, int informationClass, ref JOBOBJECT_EXTENDED_LIMIT_INFORMATION information, uint length);
    [DllImport("kernel32.dll", SetLastError = true)] [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool QueryInformationJobObject(IntPtr job, int informationClass, out JOBOBJECT_BASIC_ACCOUNTING_INFORMATION information, uint length, out uint returned);
    [DllImport("kernel32.dll", SetLastError = true)] [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool CreatePipe(out IntPtr read, out IntPtr write, ref SECURITY_ATTRIBUTES attributes, uint size);
    [DllImport("kernel32.dll", SetLastError = true)] [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool SetHandleInformation(IntPtr handle, uint mask, uint flags);
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)] [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool CreateProcess(string application, StringBuilder command, IntPtr processAttributes, IntPtr threadAttributes, bool inheritHandles, uint flags, IntPtr environment, string directory, ref STARTUPINFOEX startup, out PROCESS_INFORMATION process);
    [DllImport("kernel32.dll", SetLastError = true)] [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool InitializeProcThreadAttributeList(IntPtr list, int count, uint flags, ref IntPtr size);
    [DllImport("kernel32.dll", SetLastError = true)] [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool UpdateProcThreadAttribute(IntPtr list, uint flags, IntPtr attribute, IntPtr value, IntPtr size, IntPtr previous, IntPtr returned);
    [DllImport("kernel32.dll")] private static extern void DeleteProcThreadAttributeList(IntPtr list);
    [DllImport("kernel32.dll", SetLastError = true)] [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool AssignProcessToJobObject(IntPtr job, IntPtr process);
    [DllImport("kernel32.dll", SetLastError = true)] private static extern uint ResumeThread(IntPtr thread);
    [DllImport("kernel32.dll", SetLastError = true)] private static extern uint WaitForSingleObject(IntPtr handle, uint milliseconds);
    [DllImport("kernel32.dll", SetLastError = true)] [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool GetExitCodeProcess(IntPtr process, out uint code);
    [DllImport("kernel32.dll", SetLastError = true)] [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool TerminateJobObject(IntPtr job, uint code);
    [DllImport("kernel32.dll", SetLastError = true)] [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool TerminateProcess(IntPtr process, uint code);
    [DllImport("kernel32.dll", SetLastError = true)] [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool CloseHandle(IntPtr handle);
}
