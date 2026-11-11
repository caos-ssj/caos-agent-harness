import React from 'react'

interface PageHeadProps { title: string; lead: string; art: string; children?: React.ReactNode }

/* The head of a page: the title, one sentence of what the page is for, the actions, and the page's own engraving.
   The hairline under it carries a short bright tick, the way the mark carries its amber one. */
export const PageHead: React.FC<PageHeadProps> = ({ title, lead, art, children }) => (
  <header className="page-head">
    <img className="head-plate" src={`/art/${art}.svg`} alt="" aria-hidden="true" />
    <div className="head-text">
      <h1>{title}</h1>
      <p>{lead}</p>
    </div>
    {children && <div className="actions">{children}</div>}
  </header>
)
