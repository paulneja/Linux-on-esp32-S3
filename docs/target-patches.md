# Target-specific patch strategy: Generic N8

## Purpose

This document describes how the **Generic N8** target is maintained in the Linux-on-esp32-S3 project. It covers the relationship to the upstream N16 implementation, target-specific changes, and basic maintenance and verification practices.

## Design decision

**Generic N8 is an independently maintained derivative implementation.**

- The upstream N16 source is the starting point and remains unchanged.
- Generic N8 is constructed by copying the upstream N16 source into `target-builds/generic-n8` and then applying Generic N8-specific patches.
- N8-specific modifications are not intended to be generalized or merged back into the N16 implementation.
- Changes to Generic N8 must not silently change the default N16 build behavior.

This is deliberately different from building a common implementation with target-dependent conditionals.

## Differences from the standard N16R8 target

The following table distinguishes **hardware constraints and adopted design decisions** from **planned optimizations**. Generic N8 is still experimental; this table is not a claim that every feature has been implemented and validated on hardware.

| Area                          | Standard N16R8                                                                | Generic N8                                                                                     | Status / notes                                                                                  |
| ----------------------------- | ----------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------- |
| Flash capacity                | 16 MB                                                                         | 8 MB                                                                                           | Hardware constraint; N8 has half the flash capacity.                                            |
| PSRAM                         | 8 MB (N16R8)                                                                  | 8 MB for the N8R8 configuration being considered                                               | The target's actual PSRAM must be checked; the name N8 alone specifies flash capacity, not RAM. |
| Source tree                   | Original upstream implementation                                              | Independent derivative copied to `target-builds/generic-n8/`                                   | Adopted design decision. N16 sources remain untouched.                                          |
| Customization                 | Original build and feature set                                                | Target-specific patches in `targets-patches/generic-n8/`                                       | Adopted patch management approach; patch application and CI still require verification.         |
| Flash layout                  | Standard 16 MB partition layout                                               | Must fit all necessary images and writable partitions into 8 MB                                | N8-specific layout and usable free space require verification against the final image sizes.    |
| Root filesystem               | Includes Bash, Dash, Nano, ncurses, MicroPython, GNU Make and other utilities | Reduced rootfs, centered on BusyBox `sh` and `vi`                                              | **Planned N8 optimization**, not a verified final package manifest.                             |
| Programs targeted for removal | Present in, or supplied by, the full N16 userspace as applicable              | Bash, Dash, Nano, ncurses, MicroPython, socat and GNU Make                                     | Planned removals; review dependent libraries and tools before finalizing.                       |
| BusyBox applets               | Standard BusyBox feature selection                                            | Further disabling unused functions, including printing, mail, dial-up/PPP, VLAN and swap tools | Proposed size reduction; exact applet selection and savings have not been established here.     |
| `/home`                       | Writable Flash-backed `/home` in the standard image                           | Retention, size and placement depend on the finalized 8 MB partition budget                    | Not yet confirmed for Generic N8; do not assume `/home` moves to RAM.                           |
| SD card                       | Not required for the standard N16R8 image                                     | Not assumed for Generic N8                                                                     | SD-equipped XIAO configurations are separate from the generic N8 target.                        |
| Maturity                      | Mainline upstream implementation                                              | Experimental derivative; not yet in regular production use                                     | CI, clean builds, image size and actual board behavior must be checked.                         |

### Compatibility objective

Generic N8 aims to retain the underlying Linux-on-ESP32-S3 architecture while accommodating a smaller flash device. **Feature parity with N16 is not an objective**: optional programs and services may be removed to meet the 8 MB limit. Conversely, Generic N8-specific changes must not alter the existing N16 build.

### Verification needed before regular use

1. Confirm the exact Generic N8 hardware variant and its actual PSRAM capacity.
2. Record the finalized N8 flash partition layout, image sizes and remaining space.
3. Compare the resulting N8 rootfs package/app-list against N16 to identify _implemented_, rather than merely planned, removals.
4. Confirm whether writable `/etc` and `/home` are retained, their capacities, and their persistence after reboot/update.
5. Run clean local and CI builds, then flash and test Generic N8 hardware; repeat the N16 build to check for regressions.

## Relevant paths

| Path                          | Role                                                          |
| ----------------------------- | ------------------------------------------------------------- |
| `target-builds/generic-n8/`   | Working source tree for the independent Generic N8 derivative |
| `targets-patches/generic-n8/` | Ordered patches specific to Generic N8                        |
| `run.sh`                      | Build entry point / target selection and orchestration        |
| `.gitignore`                  | Excludes generated build products as appropriate              |

The paths above reflect the adopted target-patch approach; refer to the current branch for the definitive patch filenames and invocation details.

## Build and patch workflow

1. Start from a clean checkout of the selected upstream N16 source revision.
2. Copy the upstream source to `target-builds/generic-n8/`.
3. Apply the patches from `targets-patches/generic-n8/` in the intended order, to the Generic N8 copy only.
4. Build Generic N8 from the resulting derivative tree.
5. Verify both Generic N8 and the unchanged N16 path.

**Important:** Patch application should be deterministic, fail on mismatch, and must never partially modify the upstream N16 source. The concrete commands and patch order are governed by the implementation in `run.sh` and the patch files.

## Patch maintenance rules

- Keep each patch focused on an understandable Generic N8 change.
- Make patch paths relative to the patch application's working directory rather than embedding a machine- or CI-specific absolute path.
- Recreate patches against the _same upstream revision_ used to generate the derivative source.
- Avoid treating a failed patch as a successful build. Investigate context drift and regenerate the affected patch when upstream changes.
- Do not modify N16 to accommodate Generic N8; put the customization in the derivative patches.

## CI and reproducibility

CI must use the same source revision, copy destination, patch order, and application working directory as the local build. A failure such as `patch does not apply` for a workflow file indicates that the patch context, the working directory, or the source revision needs to be checked; it does not by itself establish which one is wrong.

Suggested verification checkpoints:

- Generic N8 patches apply cleanly to a fresh copy.
- N16 files remain unchanged after preparation and build.
- Generic N8 produces the expected build artifacts.
- N16 continues to follow its original build path.

## Scope

This document records the **adopted architecture and maintenance policy**. It does not assert that any particular Generic N8 patch or CI workflow has already passed verification; use the branch's CI results and hardware tests for that determination.

## Future plans

The following target-selection options are planned for future development and are **not yet available as fully implemented, verified build options**:

- **Client-only build:** Add a selectable build configuration dedicated to client functionality.
- **XIAO ESP32-S3:** Allow the XIAO board configuration to be selected as a build target.
- **XIAO ESP32-S3 with Sean's daughterboard and SD card:** Add a separate selectable target that supports the SD-equipped hardware configuration.

These options will be added to the build target selector as development progresses. Their availability and behavior must be confirmed through build and hardware testing before they are treated as supported configurations.
