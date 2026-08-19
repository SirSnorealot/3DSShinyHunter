#include <3ds.h>
#include <CTRPluginFramework.hpp>

#include <arpa/inet.h>
#include <errno.h>
#include <netinet/in.h>
#include <sys/socket.h>
#include <unistd.h>
#include <malloc.h>

#include <cstring>

using namespace CTRPluginFramework;

namespace
{
    constexpr u16 kPort = 4951;
    constexpr u8  kVersion = 1;
    constexpr size_t kMaxRead = 512;

    constexpr u32 kPartyBase   = 0x33F7FA44;
    constexpr u32 kPartyStride = 484;
    constexpr u32 kPk7CoreSize = 232;
    constexpr u32 kOpponent1   = 0x3254F4AC;
    constexpr u32 kOpponent2   = 0x32663BF0;

    enum Command : u8
    {
        Ping = 1,
        Read = 2,
    };

    enum Status : u8
    {
        Ok = 0,
        BadRequest = 1,
        Unsupported = 2,
        Denied = 3,
    };

#pragma pack(push, 1)
    struct Request
    {
        char magic[4];       // "SH3D"
        u8 version;
        u8 command;
        u16 flags;
        u32 requestId;
        u32 address;
        u32 size;
    };

    struct Response
    {
        char magic[4];       // "SH3D"
        u8 version;
        u8 status;
        u16 reserved;
        u32 requestId;
        u32 payloadSize;
    };
#pragma pack(pop)

    // socInit() expects an aligned work buffer that it can hand to SOC:u.
    // Do NOT place this in plugin .bss: a static plugin mapping is not a
    // suitable SOC shared-memory work area and can trigger a libctru panic.
    // 64 KiB is enough for this tiny UDP request/reply bridge.
    constexpr size_t kSocBufferSize = 0x10000; // 64 KiB
    u32 *gSocBuffer = nullptr;

    volatile bool gRunning = false;
    volatile bool gProcessExiting = false;
    Thread gServerThread = nullptr;
    int gSocket = -1;
    bool gSocInitialized = false;
    bool gSrvInitialized = false;

    bool IsAllowedRead(u32 address, u32 size)
    {
        // First version intentionally exposes only the PK7 records already
        // used by 3DSShinyHunter. It is not a general-purpose RAM server.
        if (size != kPk7CoreSize)
            return false;

        for (u32 slot = 0; slot < 6; ++slot)
        {
            if (address == kPartyBase + slot * kPartyStride)
                return true;
        }

        return address == kOpponent1 || address == kOpponent2;
    }

    void SendReply(const sockaddr_in &peer, socklen_t peerLen, u32 requestId,
                   Status status, const void *payload, u32 payloadSize)
    {
        u8 packet[sizeof(Response) + kMaxRead];
        Response response{};
        std::memcpy(response.magic, "SH3D", 4);
        response.version = kVersion;
        response.status = status;
        response.requestId = requestId;
        response.payloadSize = payloadSize;

        std::memcpy(packet, &response, sizeof(response));
        if (payload && payloadSize)
            std::memcpy(packet + sizeof(response), payload, payloadSize);

        sendto(gSocket, packet, sizeof(response) + payloadSize, 0,
               reinterpret_cast<const sockaddr *>(&peer), peerLen);
    }

    void ServerMain(void *)
    {
        while (gRunning)
        {
            Request request{};
            sockaddr_in peer{};
            socklen_t peerLen = sizeof(peer);
            const int received = recvfrom(
                gSocket, &request, sizeof(request), 0,
                reinterpret_cast<sockaddr *>(&peer), &peerLen);

            if (received < 0)
            {
                if (!gRunning)
                    break;
                svcSleepThread(10000000LL); // 10 ms
                continue;
            }

            if (received != static_cast<int>(sizeof(Request)) ||
                std::memcmp(request.magic, "SH3D", 4) != 0 ||
                request.version != kVersion)
            {
                SendReply(peer, peerLen, request.requestId, BadRequest, nullptr, 0);
                continue;
            }

            if (request.command == Ping)
            {
                static const char hello[] = "3DSShinyHunter Ultra Moon plugin v1";
                SendReply(peer, peerLen, request.requestId, Ok,
                          hello, sizeof(hello) - 1);
                continue;
            }

            if (request.command != Read)
            {
                SendReply(peer, peerLen, request.requestId, Unsupported, nullptr, 0);
                continue;
            }

            if (request.size > kMaxRead || !IsAllowedRead(request.address, request.size))
            {
                SendReply(peer, peerLen, request.requestId, Denied, nullptr, 0);
                continue;
            }

            // A 3GX plugin executes inside the game's process, so these are
            // the same virtual addresses the GDB backend previously read.
            // Copying only the validated PK7-sized regions keeps the bridge tiny.
            u8 data[kMaxRead];
            std::memcpy(data,
                        reinterpret_cast<const void *>(request.address),
                        request.size);
            SendReply(peer, peerLen, request.requestId, Ok, data, request.size);
        }
    }

    void CleanupNetwork()
    {
        if (gSocket >= 0)
        {
            shutdown(gSocket, SHUT_RDWR);
            close(gSocket);
            gSocket = -1;
        }

        if (gSocInitialized)
        {
            socExit();
            gSocInitialized = false;
        }

        if (gSocBuffer)
        {
            free(gSocBuffer);
            gSocBuffer = nullptr;
        }

        if (gSrvInitialized)
        {
            srvExit();
            gSrvInitialized = false;
        }

    }

    bool StartServer()
    {
        if (gRunning)
            return true;

        // CTRPF plugins are not normal libctru applications, so explicitly
        // initialize the service manager before asking libctru for soc:U.
        OSD::Notify("3DSShinyHunter: srvInit");
        const Result srvResult = srvInit();
        if (R_FAILED(srvResult))
        {
            OSD::Notify(Utils::Format("3DSShinyHunter: srvInit failed %08lX", (unsigned long)srvResult));
            return false;
        }
        gSrvInitialized = true;

        // The original 1 MiB allocation was too large inside USUM. The next
        // attempt used a static .bss buffer, but socInit() requires a proper
        // aligned work allocation and can panic when given arbitrary plugin
        // mapped storage. Allocate the same way libctru examples do, only much
        // smaller for our tiny UDP protocol.
        OSD::Notify("3DSShinyHunter: plugin memory=5 MiB");
        OSD::Notify("3DSShinyHunter: allocating 64 KiB SOC buffer");
        gSocBuffer = static_cast<u32 *>(memalign(0x1000, kSocBufferSize));
        if (!gSocBuffer)
        {
            OSD::Notify("3DSShinyHunter: 64 KiB SOC allocation failed");
            CleanupNetwork();
            return false;
        }
        std::memset(gSocBuffer, 0, kSocBufferSize);
        OSD::Notify("3DSShinyHunter: SOC buffer allocated");

        OSD::Notify("3DSShinyHunter: socInit");
        const Result socResult = socInit(gSocBuffer, kSocBufferSize);
        if (R_FAILED(socResult))
        {
            OSD::Notify(Utils::Format("3DSShinyHunter: socInit failed %08lX", (unsigned long)socResult));
            CleanupNetwork();
            return false;
        }
        gSocInitialized = true;

        OSD::Notify("3DSShinyHunter: socket");
        // Luma's InputRedirection retries socket creation because SOC can take
        // a short moment to become usable after initialization.
        for (int attempt = 0; attempt < 15 && gSocket < 0; ++attempt)
        {
            gSocket = socket(AF_INET, SOCK_DGRAM, 0);
            if (gSocket < 0)
                svcSleepThread(100000000LL); // 100 ms
        }
        if (gSocket < 0)
        {
            OSD::Notify(Utils::Format("3DSShinyHunter: socket failed errno=%d", errno));
            CleanupNetwork();
            return false;
        }

        sockaddr_in local{};
        local.sin_family = AF_INET;
        // Match devkitPro's socket example and Rosalina InputRedirection:
        // bind to the console's actual Wi-Fi address instead of INADDR_ANY.
        local.sin_addr.s_addr = gethostid();
        local.sin_port = htons(kPort);

        OSD::Notify(Utils::Format("3DSShinyHunter: bind UDP %d", kPort));
        if (bind(gSocket, reinterpret_cast<sockaddr *>(&local), sizeof(local)) < 0)
        {
            OSD::Notify(Utils::Format("3DSShinyHunter: bind failed errno=%d", errno));
            CleanupNetwork();
            return false;
        }

        OSD::Notify("3DSShinyHunter: starting server thread");
        gRunning = true;
        gServerThread = threadCreate(
            ServerMain, nullptr, 32 * 1024, 0x30, -2, true);
        if (!gServerThread)
        {
            OSD::Notify("3DSShinyHunter: threadCreate failed");
            gRunning = false;
            CleanupNetwork();
            return false;
        }

        OSD::Notify("3DSShinyHunter: UDP 4951 ready");
        return true;
    }

    void SignalProcessExit()
    {
        // CTRPF calls OnProcessExit while the title is already tearing down.
        // Do the absolute minimum here: tell our loops to finish and wake the
        // blocking recvfrom(). The process will reclaim sockets, threads, SOC
        // state and heap allocations itself a moment later.
        gProcessExiting = true;
        gRunning = false;

        if (gSocket >= 0)
            shutdown(gSocket, SHUT_RDWR);
    }
}

namespace CTRPluginFramework
{
    void PatchProcess(FwkSettings &settings)
    {
        // No game code patches are required. The bridge is read-only.
        (void)settings;
    }

    // CTRPluginFramework's current lifecycle callback is OnProcessExit.
    // Keep it non-blocking: signal the worker and wake recvfrom(), then let
    // the title/plugin teardown reclaim the remaining process resources.
    void OnProcessExit(void)
    {
        SignalProcessExit();
    }

    int main(void)
    {
        // This plugin is intentionally headless. We do not construct a
        // CTRPluginFramework PluginMenu or use OSD rendering because the
        // bridge has no interactive UI. Avoiding that path also minimizes
        // framework initialization inside Pokemon USUM.
        if (!StartServer())
        {
            OSD::Notify("3DSShinyHunter: network bridge NOT running");
            // Stay loaded for diagnostics, but still cooperate with a title
            // reset instead of trapping the process in an infinite loop.
            while (!gProcessExiting)
                svcSleepThread(50000000LL); // 50 ms
            return 0;
        }

        // No explicit cleanup on process exit. OnProcessExit wakes the UDP
        // worker and flips this flag; returning promptly is safer than calling
        // threadJoin/socExit/free while Horizon is destroying the title.
        while (!gProcessExiting)
            svcSleepThread(50000000LL); // 50 ms

        return 0;
    }
}
