import { formatFloat } from "@web/core/utils/numbers";
import { parseFloat as parseLocalizedFloat } from "@web/views/fields/parsers";

/** Hours follow the person's language: 7.5 in English, 7,5 in French. */
export function hours(value) {
    return formatFloat(value || 0, { digits: [false, 2], trailingZeros: false });
}

/** What a person typed, read in their language; NaN when it is no number. */
export function readHours(text) {
    const trimmed = (text || "").trim();
    if (!trimmed) {
        return 0;
    }
    try {
        return parseLocalizedFloat(trimmed);
    } catch {
        return NaN;
    }
}

/** DD/MM/YYYY to the server's YYYY-MM-DD, in every language; false when it is no date. */
export function readDate(text) {
    const match = /^(\d{2})\/(\d{2})\/(\d{4})$/.exec((text || "").trim());
    return match ? `${match[3]}-${match[2]}-${match[1]}` : false;
}

export function showDate(iso) {
    const [y, m, d] = iso.split("-");
    return `${d}/${m}/${y}`;
}

/** The refusal's own words, shown on the screen rather than in a dialog. */
export function refusal(error) {
    return error?.data?.message || error?.message || String(error);
}
