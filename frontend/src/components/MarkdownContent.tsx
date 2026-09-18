import Markdown from "react-markdown";

interface MarkdownContentProps {
  content: string;
  className?: string;
}

export function MarkdownContent({ content, className = "" }: MarkdownContentProps) {
  return <div className={`markdown-content ${className}`.trim()}>
    <Markdown
      skipHtml
      components={{
        a: ({ children, href }) => <a href={href} target="_blank" rel="noreferrer">{children}</a>,
      }}
    >
      {content}
    </Markdown>
  </div>;
}
