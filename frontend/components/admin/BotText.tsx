import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

/** A bot answer as the customer saw it (formatted), with [n] citations left as plain text. */
export function BotText({ text, className = "" }: { text: string; className?: string }) {
  return (
    <div className={`answer max-w-none text-sm ${className}`}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          a: ({ href, children }) => (
            <a href={href} target="_blank" rel="noopener noreferrer" className="underline">
              {children}
            </a>
          ),
          table: ({ children }) => (
            <div className="overflow-x-auto">
              <table>{children}</table>
            </div>
          ),
        }}
      >
        {text}
      </ReactMarkdown>
    </div>
  );
}
