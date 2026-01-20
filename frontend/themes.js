/**
 * ARTIFACT LIVE - THEME CONFIGURATION
 *
 * Theme color definitions for the UI.
 * Based on Digital Harvest/Perfect Books theme system.
 *
 * HOW TO ADD A NEW THEME:
 * 1. Copy an existing theme object
 * 2. Change the name and colors
 * 3. Add it to the THEMES object
 */

const THEMES = {
    classic: {
        name: 'Classic Cyan',
        colors: {
            bg: '#111827',
            bgSecondary: '#1f2937',
            bgTertiary: '#374151',
            bgHover: '#4b5563',
            text: '#f9fafb',
            textSecondary: '#d1d5db',
            textMuted: '#9ca3af',
            border: '#4b5563',
            borderLight: '#374151',
            primary: '#06b6d4',
            primaryHover: '#0891b2',
            primaryLight: '#22d3ee',
            success: '#10b981',
            successLight: '#34d399',
            danger: '#ef4444',
            dangerLight: '#f87171',
            warning: '#f59e0b',
            warningLight: '#fbbf24',
        }
    },

    midnight: {
        name: 'Midnight Purple',
        colors: {
            bg: '#0f0820',
            bgSecondary: '#1a1033',
            bgTertiary: '#2d1b4e',
            bgHover: '#3d2563',
            text: '#f0e6ff',
            textSecondary: '#c7b8ea',
            textMuted: '#9d8ec4',
            border: '#4c3575',
            borderLight: '#3d2563',
            primary: '#a855f7',
            primaryHover: '#9333ea',
            primaryLight: '#c084fc',
            success: '#10b981',
            successLight: '#34d399',
            danger: '#f43f5e',
            dangerLight: '#fb7185',
            warning: '#f59e0b',
            warningLight: '#fbbf24',
        }
    },

    emerald: {
        name: 'Emerald',
        colors: {
            bg: '#0a1410',
            bgSecondary: '#0f2419',
            bgTertiary: '#1a3d2e',
            bgHover: '#27543f',
            text: '#f0fdf4',
            textSecondary: '#d1fae5',
            textMuted: '#a7f3d0',
            border: '#34704f',
            borderLight: '#27543f',
            primary: '#10b981',
            primaryHover: '#059669',
            primaryLight: '#34d399',
            success: '#22c55e',
            successLight: '#4ade80',
            danger: '#ef4444',
            dangerLight: '#f87171',
            warning: '#f59e0b',
            warningLight: '#fbbf24',
        }
    },

    amber: {
        name: 'Amber',
        colors: {
            bg: '#1c1410',
            bgSecondary: '#2d2318',
            bgTertiary: '#44362a',
            bgHover: '#5c4939',
            text: '#fef3c7',
            textSecondary: '#fde68a',
            textMuted: '#fcd34d',
            border: '#78644e',
            borderLight: '#5c4939',
            primary: '#f59e0b',
            primaryHover: '#d97706',
            primaryLight: '#fbbf24',
            success: '#10b981',
            successLight: '#34d399',
            danger: '#dc2626',
            dangerLight: '#ef4444',
            warning: '#ea580c',
            warningLight: '#f97316',
        }
    },

    rose: {
        name: 'Rose',
        colors: {
            bg: '#1a0d14',
            bgSecondary: '#2d1823',
            bgTertiary: '#4a2d3d',
            bgHover: '#5e3a51',
            text: '#fef2f2',
            textSecondary: '#fecdd3',
            textMuted: '#fda4af',
            border: '#9f4d70',
            borderLight: '#7c3a5a',
            primary: '#f43f5e',
            primaryHover: '#e11d48',
            primaryLight: '#fb7185',
            success: '#10b981',
            successLight: '#34d399',
            danger: '#dc2626',
            dangerLight: '#ef4444',
            warning: '#f59e0b',
            warningLight: '#fbbf24',
        }
    },

    slate: {
        name: 'Slate',
        colors: {
            bg: '#0f0f0f',
            bgSecondary: '#1a1a1a',
            bgTertiary: '#262626',
            bgHover: '#333333',
            text: '#fafafa',
            textSecondary: '#d4d4d4',
            textMuted: '#a3a3a3',
            border: '#404040',
            borderLight: '#333333',
            primary: '#64748b',
            primaryHover: '#475569',
            primaryLight: '#94a3b8',
            success: '#10b981',
            successLight: '#34d399',
            danger: '#ef4444',
            dangerLight: '#f87171',
            warning: '#f59e0b',
            warningLight: '#fbbf24',
        }
    }
};

const DEFAULT_THEME = 'classic';

if (typeof module !== 'undefined' && module.exports) {
    module.exports = { THEMES, DEFAULT_THEME };
}
