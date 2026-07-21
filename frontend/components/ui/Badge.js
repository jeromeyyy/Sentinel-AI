import * as React from "react"
import { cva } from "class-variance-authority"
import { cn } from "../../lib/utils"
import { PRIORITY_COLORS } from "../../lib/constants"

const badgeVariants = cva(
  "inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-semibold transition-colors focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2",
  {
    variants: {
      variant: {
        default: "border-transparent bg-primary text-primary-foreground hover:bg-primary/80",
        secondary: "border-transparent bg-secondary text-secondary-foreground hover:bg-secondary/80",
        destructive: "border-transparent bg-red-500/20 text-red-400 hover:bg-red-500/30 border-red-500/50",
        outline: "text-foreground border-border",
        // Legacy support
        critical: "border-critical/50 bg-critical/20 text-critical",
        high: "border-high/50 bg-high/20 text-high",
        medium: "border-medium/50 bg-medium/20 text-medium",
        low: "border-low/50 bg-low/20 text-low",
        success: "border-success/50 bg-success/20 text-success",
        online: "border-transparent bg-success/20 text-success",
        offline: "border-transparent bg-critical/20 text-critical",
      },
      size: {
        default: "px-2.5 py-0.5 text-xs",
        sm: "px-1.5 py-0.5 text-[10px]",
        md: "px-2 py-1 text-xs",
        lg: "px-3 py-1.5 text-sm",
      }
    },
    defaultVariants: {
      variant: "default",
      size: "default",
    },
  }
)

function Badge({ className, variant, size, dot, pulse, children, ...props }) {
  return (
    <div className={cn(badgeVariants({ variant, size }), className)} {...props}>
      {dot && (
        <span
          className={cn(
            "w-1.5 h-1.5 rounded-full mr-1.5",
            variant === "online" || variant === "success" ? "bg-success" :
            variant === "offline" || variant === "critical" || variant === "destructive" ? "bg-critical" :
            variant === "high" ? "bg-high" :
            variant === "medium" ? "bg-medium" :
            variant === "low" ? "bg-low" : "bg-current",
            pulse && "animate-pulse"
          )}
        />
      )}
      {children}
    </div>
  )
}

export { Badge, badgeVariants }
