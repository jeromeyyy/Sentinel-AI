module.exports = {
  content: [
    "./pages/**/*.{js,ts,jsx,tsx}",
    "./components/**/*.{js,ts,jsx,tsx}",
    "./contexts/**/*.{js,ts,jsx,tsx}",
    "./hooks/**/*.{js,ts,jsx,tsx}",
  ],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        // Dynamic theme colors using CSS variables
        background: 'var(--bg-primary)',
        foreground: 'var(--text-primary)',
        card: 'var(--bg-secondary)',
        'card-hover': 'var(--bg-tertiary)',
        muted: 'var(--bg-tertiary)',
        'muted-foreground': 'var(--text-secondary)',
        border: 'var(--border-color)',
        'border-hover': 'var(--border-hover)',
        input: 'var(--border-color)',
        ring: 'var(--accent-blue)',
        primary: 'var(--accent-blue)',
        'primary-foreground': '#ffffff',
        secondary: 'var(--bg-tertiary)',
        'secondary-foreground': 'var(--text-primary)',
        destructive: 'var(--accent-red)',
        'destructive-foreground': '#ffffff',
        
        // Priority colors
        critical: '#f4212e',
        high: '#ff7a00',
        medium: '#ffd400',
        low: '#1d9bf0',
        
        // Status colors
        success: '#00ba7c',
        warning: '#ffd400',
        danger: '#f4212e',
        info: '#1d9bf0',
      },
      animation: {
        'pulse-slow': 'pulse 3s cubic-bezier(0.4, 0, 0.6, 1) infinite',
        'slide-in': 'slideIn 0.3s ease-out',
        'slide-out': 'slideOut 0.3s ease-in',
        'slide-in-right': 'slideInRight 0.3s ease-out',
        'slide-out-right': 'slideOutRight 0.3s ease-in',
        'slide-up': 'slideUp 0.3s ease-out',
        'fade-in': 'fadeIn 0.2s ease-out',
        'fade-in-slow': 'fadeIn 0.5s ease-out',
        'scale-in': 'scaleIn 0.2s ease-out',
        'counter': 'counter 0.5s ease-out',
        'shimmer': 'shimmer 2s infinite linear',
        'float': 'float 6s ease-in-out infinite',
        'glow-pulse': 'glowPulse 2s ease-in-out infinite',
        'border-glow': 'borderGlow 3s ease-in-out infinite',
      },
      keyframes: {
        slideIn: {
          '0%': { transform: 'translateX(100%)', opacity: '0' },
          '100%': { transform: 'translateX(0)', opacity: '1' },
        },
        slideOut: {
          '0%': { transform: 'translateX(0)', opacity: '1' },
          '100%': { transform: 'translateX(100%)', opacity: '0' },
        },
        slideInRight: {
          '0%': { transform: 'translateX(-20px)', opacity: '0' },
          '100%': { transform: 'translateX(0)', opacity: '1' },
        },
        slideOutRight: {
          '0%': { transform: 'translateX(0)', opacity: '1' },
          '100%': { transform: 'translateX(20px)', opacity: '0' },
        },
        slideUp: {
          '0%': { transform: 'translateY(20px)', opacity: '0' },
          '100%': { transform: 'translateY(0)', opacity: '1' },
        },
        fadeIn: {
          '0%': { opacity: '0' },
          '100%': { opacity: '1' },
        },
        scaleIn: {
          '0%': { transform: 'scale(0.95)', opacity: '0' },
          '100%': { transform: 'scale(1)', opacity: '1' },
        },
        shimmer: {
          '0%': { backgroundPosition: '-200% 0' },
          '100%': { backgroundPosition: '200% 0' },
        },
        float: {
          '0%, 100%': { transform: 'translateY(0)' },
          '50%': { transform: 'translateY(-10px)' },
        },
        glowPulse: {
          '0%, 100%': { boxShadow: '0 0 20px rgba(29, 155, 240, 0.3)' },
          '50%': { boxShadow: '0 0 40px rgba(29, 155, 240, 0.5)' },
        },
        borderGlow: {
          '0%, 100%': { borderColor: 'rgba(29, 155, 240, 0.3)' },
          '50%': { borderColor: 'rgba(29, 155, 240, 0.6)' },
        },
      },
      boxShadow: {
        'glow-red': '0 0 20px rgba(244, 33, 46, 0.3)',
        'glow-blue': '0 0 20px rgba(29, 155, 240, 0.3)',
        'glow-green': '0 0 20px rgba(0, 186, 124, 0.3)',
        'glow-purple': '0 0 20px rgba(147, 51, 234, 0.3)',
        'glow-orange': '0 0 20px rgba(255, 122, 0, 0.3)',
        'inner-glow': 'inset 0 0 20px rgba(29, 155, 240, 0.1)',
        'glass': '0 8px 32px rgba(0, 0, 0, 0.3)',
        'glass-lg': '0 12px 48px rgba(0, 0, 0, 0.4)',
      },
      backdropBlur: {
        xs: '2px',
      },
      borderRadius: {
        '4xl': '2rem',
      },
    },
  },
  plugins: [],
};
