import { NextRequest, NextResponse } from 'next/server';
import fs from 'fs';
import path from 'path';

/**
 * Catch-all API route for static snapshot fallback
 * Serves data from pre-exported JSON snapshot files
 *
 * Route mapping:
 *   GET /api/data/kr/signals      → data-snapshot/kr-signals.json
 *   GET /api/data/us/market-gate  → data-snapshot/us-market-gate.json
 *   GET /api/data/crypto/briefing → data-snapshot/crypto-briefing.json
 */

const SNAPSHOT_DIR = path.join(process.cwd(), 'data-snapshot');

// Map API paths to snapshot filenames
function getSnapshotFile(segments: string[]): string {
    const key = segments.join('-');
    return path.join(SNAPSHOT_DIR, `${key}.json`);
}

export async function GET(
    request: NextRequest,
    { params }: { params: Promise<{ path: string[] }> }
) {
    try {
        const { path: segments } = await params;
        const filePath = getSnapshotFile(segments);

        if (!fs.existsSync(filePath)) {
            return NextResponse.json(
                { error: 'Data not available', path: segments.join('/') },
                { status: 404 }
            );
        }

        const data = JSON.parse(fs.readFileSync(filePath, 'utf-8'));
        return NextResponse.json(data, {
            headers: {
                'Cache-Control': 'public, s-maxage=300, stale-while-revalidate=600',
            },
        });
    } catch (error) {
        return NextResponse.json(
            { error: 'Failed to load data' },
            { status: 500 }
        );
    }
}

export async function POST(
    request: NextRequest,
    { params }: { params: Promise<{ path: string[] }> }
) {
    // POST endpoints return empty data in static snapshot mode
    return NextResponse.json({ message: 'Static deployment - POST not available' });
}
