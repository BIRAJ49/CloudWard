import type { ButtonHTMLAttributes, ReactNode } from "react";
import { Link } from "react-router-dom";

interface ArrowFillButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  children: ReactNode;
  className?: string;
  href?: string;
  to?: string;
}

function ButtonContents({ children }: { children: ReactNode }) {
  return (
    <>
      <span className="obsidian-arrow-button__text">{children}</span>
      <span className="obsidian-arrow-button__fill" aria-hidden="true">
        <span>{children}</span>
        <svg viewBox="0 0 10 10" focusable="false">
          <path d="M0 5.625h7.625l-3.5 3.5L5 10l5-5-5-5-.875.875 3.5 3.5H0v1.25Z" />
          <path d="M0 5.625h7.625l-3.5 3.5L5 10l5-5-5-5-.875.875 3.5 3.5H0v1.25Z" />
        </svg>
      </span>
    </>
  );
}

/**
 * Adapted for React Router from ObsidianUI's MIT-licensed Arrow Fill Button.
 * https://www.obsidianui.dev/docs/arrow-fill-button
 */
export function ArrowFillButton({ children, className = "", href, to, type = "button", ...props }: ArrowFillButtonProps) {
  const classes = `obsidian-arrow-button ${className}`.trim();

  if (to) {
    return <Link className={classes} to={to}><ButtonContents>{children}</ButtonContents></Link>;
  }

  if (href) {
    return <a className={classes} href={href}><ButtonContents>{children}</ButtonContents></a>;
  }

  return <button {...props} className={classes} type={type}><ButtonContents>{children}</ButtonContents></button>;
}
