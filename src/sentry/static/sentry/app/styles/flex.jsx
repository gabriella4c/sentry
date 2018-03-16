import {css} from 'react-emotion';

export const flex = css`
  display: flex;
`;

export const alignItemsCenter = css`
  align-items: center;
  ${flex};
`;

export const justifyContentCenter = css`
  align-items: justifyContentCenter;
  ${flex};
`;

export const justifyContentSpaceBetween = css`
  justify-content: space-between;
  ${flex};
`;
