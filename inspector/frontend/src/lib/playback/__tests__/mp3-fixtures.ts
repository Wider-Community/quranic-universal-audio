/** Synthetic MP3 heads for the play-url / mp3-header tests. */

/** MPEG-1 Layer III, 128 kbps, 44.1 kHz, joint stereo — side info 32 bytes. */
export const MPEG1_STEREO = [0xff, 0xfb, 0x90, 0x64];
/** MPEG-1 Layer III mono — side info 17 bytes. */
export const MPEG1_MONO = [0xff, 0xfb, 0x90, 0xc4];
/** MPEG-2 Layer III, 64 kbps, 22.05 kHz, stereo — side info 17 bytes. */
export const MPEG2_STEREO = [0xff, 0xf3, 0x80, 0x64];

export function ascii(s: string): number[] {
    return [...s].map((c) => c.charCodeAt(0));
}

export function id3v2(payloadBytes: number, footer = false): number[] {
    const size = [
        (payloadBytes >> 21) & 0x7f, (payloadBytes >> 14) & 0x7f,
        (payloadBytes >> 7) & 0x7f, payloadBytes & 0x7f,
    ];
    return [...ascii('ID3'), 0x04, 0x00, footer ? 0x10 : 0x00, ...size,
        ...new Array<number>(payloadBytes).fill(0x00),
        ...(footer ? [...ascii('3DI'), 0x04, 0x00, 0x10, ...size] : [])];
}

export function frame(header: number[], sideInfo: number, tag: string | null): number[] {
    return [...header, ...new Array<number>(sideInfo).fill(0x00),
        ...(tag ? ascii(tag) : [0, 0, 0, 0]), ...new Array<number>(64).fill(0xaa)];
}

export function mp3Head(opts: {
    tag: string | null; id3?: number; header?: number[]; sideInfo?: number;
}): Uint8Array {
    const { tag, id3 = 0, header = MPEG1_STEREO, sideInfo = 32 } = opts;
    return new Uint8Array([...(id3 ? id3v2(id3) : []), ...frame(header, sideInfo, tag)]);
}
