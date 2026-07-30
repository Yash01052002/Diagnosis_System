import { forwardRef, useId } from "react";
import { cx } from "../lib/cx";

const fieldBase =
  "w-full rounded-lg border border-token surface px-3 py-2 text-sm text-[color:var(--text)] placeholder:text-[color:var(--text-muted)] focus:outline-none focus:ring-2 focus:ring-brand-500 disabled:opacity-60";

export interface InputProps
  extends React.InputHTMLAttributes<HTMLInputElement> {
  label?: string;
  error?: string | null;
  hint?: string;
}

export const Input = forwardRef<HTMLInputElement, InputProps>(
  ({ label, error, hint, className, id, ...rest }, ref) => {
    const generated = useId();
    const inputId = id ?? generated;
    return (
      <div className="flex flex-col gap-1">
        {label && (
          <label htmlFor={inputId} className="text-sm font-medium">
            {label}
          </label>
        )}
        <input
          ref={ref}
          id={inputId}
          aria-invalid={error ? true : undefined}
          className={cx(fieldBase, error && "border-red-500 focus:ring-red-500", className)}
          {...rest}
        />
        {error ? (
          <p className="text-xs text-red-500">{error}</p>
        ) : hint ? (
          <p className="text-xs text-muted">{hint}</p>
        ) : null}
      </div>
    );
  },
);
Input.displayName = "Input";

export interface SelectProps
  extends React.SelectHTMLAttributes<HTMLSelectElement> {
  label?: string;
}

export const Select = forwardRef<HTMLSelectElement, SelectProps>(
  ({ label, className, id, children, ...rest }, ref) => {
    const generated = useId();
    const selectId = id ?? generated;
    return (
      <div className="flex flex-col gap-1">
        {label && (
          <label htmlFor={selectId} className="text-sm font-medium">
            {label}
          </label>
        )}
        <select ref={ref} id={selectId} className={cx(fieldBase, className)} {...rest}>
          {children}
        </select>
      </div>
    );
  },
);
Select.displayName = "Select";

export interface TextareaProps
  extends React.TextareaHTMLAttributes<HTMLTextAreaElement> {
  label?: string;
  error?: string | null;
}

export const Textarea = forwardRef<HTMLTextAreaElement, TextareaProps>(
  ({ label, error, className, id, ...rest }, ref) => {
    const generated = useId();
    const areaId = id ?? generated;
    return (
      <div className="flex flex-col gap-1">
        {label && (
          <label htmlFor={areaId} className="text-sm font-medium">
            {label}
          </label>
        )}
        <textarea
          ref={ref}
          id={areaId}
          className={cx(fieldBase, "min-h-24 resize-y", error && "border-red-500", className)}
          {...rest}
        />
        {error && <p className="text-xs text-red-500">{error}</p>}
      </div>
    );
  },
);
Textarea.displayName = "Textarea";
