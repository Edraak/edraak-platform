import { ReactRenderer } from 'ReactRenderer';
import  UnsubscribeMarketingEmail  from "./components/UnsubscribeMarketingEmail";

const maxWait = 60000;
const interval = 50;
const unsubscribeMarketingEmailWrapperId = 'unsubscribe-marketing-email-container';
let currentWait = 0;

const wrapperRendered = setInterval(() => {
  const wrapper = document.getElementById(unsubscribeMarketingEmailWrapperId);

  if (wrapper) {
    clearInterval(wrapperRendered);
    new ReactRenderer({
      component: UnsubscribeMarketingEmail,
      selector: `#${unsubscribeMarketingEmailWrapperId}`,
      componentName: 'UnsubscribeMarketingEmail',
      // The props should be the state of learner if subscribed or not but this one only for testing
      props: { isUserSubscribed: window.isUserSubscribed, userEmail: window.userEmail },
    });
  }

  currentWait += interval;

  if (currentWait >= maxWait) {
    clearInterval(wrapperRendered);
  }
}, interval);
