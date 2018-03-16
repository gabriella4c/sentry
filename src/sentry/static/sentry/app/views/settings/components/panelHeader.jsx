import PropTypes from 'prop-types';
import React from 'react';
import styled from 'react-emotion';
import {
  verticalPadding,
  verticalPaddingSmall,
  horizontalPadding,
} from '../../../styles/padding';
import {flex} from '../../../styles/flex';

import PanelHeading from './panelHeading';

const StyledPanelHeader = styled(({disablePadding, hasButtons, ...props}) => (
  <div {...props} />
))`
  ${p => (p.hasButtons ? verticalPaddingSmall : verticalPadding)};
  ${p => !p.disablePadding && horizontalPadding};
  border-bottom: 1px solid ${p => p.theme.borderDark};
  border-radius: ${p => p.theme.borderRadius} ${p => p.theme.borderRadius} 0 0;
  background: ${p => p.theme.offWhite};
  text-transform: uppercase;
  font-size: 13px;
  line-height: 1;
`;

const StyledPanelHeading = styled(({lightText, isFlex, align, justify, ...props}) => (
  <PanelHeading {...props} />
))`
  font-size: inherit;
  text-transform: inherit;
  margin: 0;
  ${p => p.isFlex && flex};
  ${p => (p.lightText ? `color: ${p.theme.gray2}` : '')};
  ${p => (p.align ? `align-items: ${p.align};` : '')};
  ${p => (p.justify ? `justify-content: ${p.justify};` : '')};
`;

class PanelHeader extends React.Component {
  render() {
    let {lightText, isFlex, align, justify, children, ...props} = this.props;

    return (
      <StyledPanelHeader {...props}>
        <StyledPanelHeading
          lightText={lightText}
          align={align}
          justify={justify}
          isFlex={isFlex}
        >
          {children}
        </StyledPanelHeading>
      </StyledPanelHeader>
    );
  }
}

PanelHeader.propTypes = {
  isFlex: PropTypes.bool,
  disablePadding: PropTypes.bool,
  hasButtons: PropTypes.bool,
  lightText: PropTypes.bool,
  align: PropTypes.string,
  justify: PropTypes.string,
};

export default PanelHeader;
