const extensionStatusJSON_bug = {
  "status": 400,
  "message": "CueMeet encountered a new error"
}
const mutationConfig = { childList: true, attributes: true, subtree: true }

let userName = "You"
overWriteChromeStorage(["userName"], false)
let transcript = []
let personNameBuffer = "", transcriptTextBuffer = "", timeStampBuffer = undefined
let beforePersonName = "", beforeTranscriptText = ""
let chatMessages = []
overWriteChromeStorage(["chatMessages"], false)

let meetingStartTimeStamp = new Date().toISOString().toUpperCase();
let meetingTitle = document.title
overWriteChromeStorage(["meetingStartTimeStamp", "meetingTitle"], false)
let isTranscriptDomErrorCaptured = false
let isChatMessagesDomErrorCaptured = false
let hasMeetingStarted = false
let hasMeetingEnded = false


const checkElement = async (selector, text) => {
  if (text) {
    while (!Array.from(document.querySelectorAll(selector)).find(element => element.textContent === text)) {
      await new Promise((resolve) => requestAnimationFrame(resolve));
    }
  }
  else {
    while (!document.querySelector(selector)) {
      await new Promise((resolve) => requestAnimationFrame(resolve));
    }
  }
  return document.querySelector(selector);
}


checkExtensionStatus();
let extensionStatusJSON = JSON.parse(localStorage.getItem('extensionStatusJSON'));
if (extensionStatusJSON) {
  console.log("Extension status " + extensionStatusJSON.status);

  if (extensionStatusJSON.status == 200) {
    checkElement(".awLEm").then(() => {
      const captureUserNameInterval = setInterval(() => {
        userName = document.querySelector(".awLEm").textContent
        if (userName || hasMeetingStarted) {
          clearInterval(captureUserNameInterval)
          if (userName != "")
            overWriteChromeStorage(["userName"], false)
        }
      }, 100)
    })

    meetingRoutines(1)

    meetingRoutines(2)
  }
  else {
    extensionStatusJSON = { status: 200, message: "<strong>CueMeet is running</strong> <br /> Do not turn off captions" };
    console.log("Extension status " + extensionStatusJSON.status);
  }
}

function checkExtensionStatus() {
  localStorage.setItem('extensionStatusJSON', JSON.stringify({
    status: 200,
    message: "<strong>CueMeet is running</strong> <br /> Do not turn off captions"
  }))
}


function meetingRoutines(uiType) {
  const meetingEndIconData = {
    selector: "",
    text: ""
  }
  const captionsIconData = {
    selector: "",
    text: ""
  }
  switch (uiType) {
    case 1:
      meetingEndIconData.selector = ".google-material-icons"
      meetingEndIconData.text = "call_end"
      captionsIconData.selector = ".material-icons-extended"
      captionsIconData.text = "closed_caption_off"
      break;
    case 2:
      meetingEndIconData.selector = ".google-symbols"
      meetingEndIconData.text = "call_end"
      captionsIconData.selector = ".google-symbols"
      captionsIconData.text = "closed_caption_off"
    default:
      break;
  }

  checkElement(meetingEndIconData.selector, meetingEndIconData.text).then(() => {
    console.log("Meeting started")
    chrome.runtime.sendMessage({ type: "new_meeting_started" }, function (response) {
      console.log(response);
    });
    hasMeetingStarted = true



    try {
      setTimeout(() => updateMeetingTitle(), 5000)
      const captionsButton = contains(captionsIconData.selector, captionsIconData.text)[0]


      let operationMode = localStorage.getItem('operationMode');
      if (operationMode == "manual")
        console.log("Manual mode selected, leaving transcript off")
      else
        captionsButton.click()

      const transcriptTargetNode = document.querySelector('[role="region"][aria-label="Captions"]')
      try {
        transcriptTargetNode.childNodes[1].style.opacity = 0.2
      } catch (error) {
        console.error(error)
      }

      function observeCaptions() {
        let userLatestMessages = {};
        let currentSpeaker = null; 
        let lastProcessedMessage = null;

        const captionsRegion = document.querySelector('[role="region"][aria-label="Captions"]');
        if (captionsRegion) {
          const transcriptObserver = new MutationObserver(() => {
            const captionContainers = document.querySelectorAll('.nMcdL.bj4p3b');
            let hasUpdates = false;
            
            const container = captionContainers[captionContainers.length - 1];
            if (container) {
              const userNameElement = container.querySelector('.NWpY1d');
              const messageElement = container.querySelector('.bh44bd.VbkSUe');
              
              if (userNameElement && messageElement) {
                const userName = userNameElement.textContent;
                const message = messageElement.textContent;
                
                const messageKey = `${userName}:${message}`;
                if (messageKey !== lastProcessedMessage && userLatestMessages[userName] !== message) {
                  const timeStamp = new Date().toISOString();
                  
                  if (currentSpeaker !== userName) {
                    transcript.push({
                      personName: userName,
                      timeStamp: timeStamp,
                      personTranscript: message
                    });
                    currentSpeaker = userName;
                  } else {
                    const lastEntry = transcript[transcript.length - 1];
                    if (lastEntry && lastEntry.personName === userName) {
                      lastEntry.timeStamp = timeStamp;
                      lastEntry.personTranscript = message;
                    }
                  }
                  
                  userLatestMessages[userName] = message;
                  lastProcessedMessage = messageKey;
                  hasUpdates = true;
                }
              }
            }
            
            if (hasUpdates) {
              overWriteChromeStorage(['transcript'], true);
            }
          });
          
          transcriptObserver.observe(captionsRegion, {
            childList: true,
            subtree: true,
            characterData: true
          });
        } else {
          setTimeout(observeCaptions, 1000);
        }
      }

      observeCaptions();

      const chatMessagesButton = contains(".google-symbols", "chat")[0]
      chatMessagesButton.click()
      let chatMessagesObserver
      setTimeout(() => {
        chatMessagesButton.click()
        try {
          const chatMessagesTargetNode = document.querySelectorAll('div[aria-live="polite"]')[0]

          chatMessagesObserver = new MutationObserver(chatMessagesRecorder)

          chatMessagesObserver.observe(chatMessagesTargetNode, mutationConfig)
        } catch (error) {
          console.error(error)
          showNotification(extensionStatusJSON_bug)
        }
      }, 500)

      if (operationMode == "manual")
        showNotification({ status: 400, message: "<strong>CueMeet is not running</strong> <br /> Turn on captions using the CC icon, if needed" })
      else
        showNotification(extensionStatusJSON)
      contains(meetingEndIconData.selector, meetingEndIconData.text)[0].parentElement.parentElement.addEventListener("click", () => {
        hasMeetingEnded = true
        transcriptObserver.disconnect()
        chatMessagesObserver.disconnect()

        if ((personNameBuffer != "") && (transcriptTextBuffer != ""))
          pushBufferToTranscript()
        overWriteChromeStorage(["transcript", "chatMessages"], true)
      })
    } catch (error) {
      console.error(error)
      showNotification(extensionStatusJSON_bug)
    }
  })
}


function contains(selector, text) {
  var elements = document.querySelectorAll(selector);
  return Array.prototype.filter.call(elements, function (element) {
    return RegExp(text).test(element.textContent);
  });
}


function showNotification(extensionStatusJSON) {
  let html = document.querySelector("html");
  let obj = document.createElement("div");
  let text = document.createElement("p");

  setTimeout(() => {
    obj.style.display = "none";
  }, 5000);

  if (extensionStatusJSON.status == 200) {
    obj.style.cssText = `color: #2A9ACA; ${commonCSS}`;
    text.innerHTML = extensionStatusJSON.message;
  }
  else {
    obj.style.cssText = `color: orange; ${commonCSS}`;
    text.innerHTML = extensionStatusJSON.message;
  }

  obj.prepend(text);
  if (html)
    html.append(obj);
}

const commonCSS = `background: rgb(255 255 255 / 10%); 
    backdrop-filter: blur(16px); 
    position: fixed;
    top: 5%; 
    left: 0; 
    right: 0; 
    margin-left: auto; 
    margin-right: auto;
    max-width: 780px;  
    z-index: 1000; 
    padding: 0rem 1rem;
    border-radius: 8px; 
    display: flex; 
    justify-content: center; 
    align-items: center; 
    gap: 16px;  
    font-size: 1rem; 
    line-height: 1.5; 
    font-family: 'Google Sans',Roboto,Arial,sans-serif; 
    box-shadow: rgba(0, 0, 0, 0.16) 0px 10px 36px 0px, rgba(0, 0, 0, 0.06) 0px 0px 0px 1px;`;

function chatMessagesRecorder(mutationsList, observer) {
  mutationsList.forEach(mutation => {
    try {
      const chatMessagesElement = document.querySelectorAll('div[aria-live="polite"]')[0]
      if (chatMessagesElement.children.length > 0) {
        const chatMessageElement = chatMessagesElement.lastChild
        const personName = chatMessageElement.firstChild.firstChild.textContent
        const timeStamp = new Date().toISOString().toUpperCase();
        const chatMessageText = chatMessageElement.lastChild.lastChild.textContent

        const chatMessageBlock = {
          personName: personName,
          timeStamp: timeStamp,
          chatMessageText: chatMessageText
        }

        pushUniqueChatBlock(chatMessageBlock)
        overWriteChromeStorage(["chatMessages", false])
      }
    }
    catch (error) {
      console.error(error)
      if (isChatMessagesDomErrorCaptured == false && hasMeetingEnded == false) {
        console.log("There is a bug in CueMeet.", error)
        showNotification(extensionStatusJSON_bug)
      }
      isChatMessagesDomErrorCaptured = true
    }
  })
}

function pushBufferToTranscript() {
  transcript.push({
    "personName": personNameBuffer,
    "timeStamp": timeStampBuffer,
    "personTranscript": transcriptTextBuffer
  })
}

function pushUniqueChatBlock(chatBlock) {
  const isExisting = chatMessages.some(item =>
    item.personName == chatBlock.personName &&
    item.timeStamp == chatBlock.timeStamp &&
    chatBlock.chatMessageText.includes(item.chatMessageText)
  )
  if (!isExisting)
    chatMessages.push(chatBlock);
}

function overWriteChromeStorage(keys, sendDownloadMessage) {
  if (keys.includes("userName"))
    localStorage.setItem('userName', JSON.stringify(userName))
  if (keys.includes("transcript"))
    localStorage.setItem('transcript', JSON.stringify(transcript))
  if (keys.includes("meetingTitle"))
    localStorage.setItem('meetingTitle', meetingTitle)
  if (keys.includes("meetingStartTimeStamp"))
    localStorage.setItem('meetingStartTimeStamp', JSON.stringify(meetingStartTimeStamp))
  if (keys.includes("chatMessages"))
    localStorage.setItem('chatMessages', JSON.stringify(chatMessages))

  if (sendDownloadMessage) {
    if (transcript.length > 0) {
      chrome.runtime.sendMessage({ type: "download" }, function (response) {
        console.log(response);
      })
    }
  }
}


function updateMeetingTitle() {
  try {
    const title = document.querySelector(".u6vdEc").textContent
    const invalidFilenameRegex = /[^\w\-_.() ]/g
    meetingTitle = title.replace(invalidFilenameRegex, '_')
    overWriteChromeStorage(["meetingTitle"], false)
  } catch (error) {
    console.error(error)
  }
}
