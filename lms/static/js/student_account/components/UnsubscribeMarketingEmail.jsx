import React from 'react';
import PropTypes from 'prop-types';
import { CheckBox } from '@edx/paragon/static';
import { unsubscribe, subscribe } from "../AccountsClient";



class UnsubscribeMarketingEmail extends React.Component {
  constructor(props) {
    super(props);
    this.state = {
      checked: props.isUserSubscribed,
    };
    this.subscribeMarketingEmail = this.subscribeMarketingEmail.bind(this);
    this.unsubscribeMarketingEmail = this.unsubscribeMarketingEmail.bind(this);
    this.handleCheckbox = this.handleCheckbox.bind(this);
  }

  handleCheckbox () {
    this.state.checked ? this.unsubscribeMarketingEmail(): this.subscribeMarketingEmail()
  }

  subscribeMarketingEmail() {
    subscribe(this.props.userEmail)
        .then(() => this.setState({
          checked: true
        }))
        .catch(error => console.log(error.message))
  }

  unsubscribeMarketingEmail() {
    unsubscribe(this.props.userEmail)
        .then(() => this.setState({
          checked: false
        }))
        .catch(error => console.log(error.message))
  }

  render() {
    const { checked } = this.state;

    return (
      <div className="account-deletion-details">
       <CheckBox
            onChange={this.handleCheckbox}
            checked={checked}
            name='unsubscribe_checkbox'
            label=''
          />
          <p className='subscription-text'>
            {gettext('Subscribe to marketing emails')}
          </p>
          <p className='subscription-text'>
            {gettext('Please note: Once your account is unsubscribed from marketing emails, you will no longer receive emails from edraak.org, or any other site hosted by Edraak.')}
          </p>
      </div>
    );
  }
}

UnsubscribeMarketingEmail.propTypes = {
  isUserSubscribed: PropTypes.bool.isRequired,
  userEmail: PropTypes.string.isRequired,
};
export default UnsubscribeMarketingEmail;
