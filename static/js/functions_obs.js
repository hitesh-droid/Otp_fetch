let selectedEmails = new Set();
let otpRefreshInterval;
let refreshTimeout;
let isFirstRequest = true;
const emailList = {{ pt_emails|tojson }};


// Handle email selection
function selectEmail() {
    const emailInput = document.getElementById('email-input');
    const email = emailInput.value.trim();

    if (email && !selectedEmails.has(email)) {
        selectedEmails.add(email);
        updateTiles(); // Function to update the tiles
        waitAndFetchOTPs(); // Start the OTP fetch with 10-second delay
        emailInput.value = '';
    } else if (!email) {
        alert("Please select a valid email.");
    }
}

// Escape special characters in email selectors
function escapeEmailSelector(email) {
    return email.replace(/[@.]/g, match => '\\' + match);
}

// Filter emails based on user input
function filterEmails() {
    const query = $('#email-input').val().toLowerCase();
    const suggestionsContainer = $('#suggestions').empty();
    if (query === "") {
        $('#suggestions').hide();
        return;
    }

    const suggestions = emailList.filter(email => email.toLowerCase().includes(query));
    suggestions.forEach(email => {
        suggestionsContainer.append(`
            <div class="suggestion-item" onclick="selectSuggestion('${email}')">${email}</div>
        `);
    });

    if (suggestions.length === 0) {
        $('#suggestions').hide();
    } else {
        $('#suggestions').show();
    }
}

// Handle selection from suggestions
function selectSuggestion(email) {
    $('#email-input').val(email);
    $('#suggestions').hide();
}

// Update the tiles container with selected emails
function updateTiles() {
    const tilesContainer = document.getElementById('email-tiles');
    tilesContainer.innerHTML = ''; // Clear previous tiles

    selectedEmails.forEach(email => {
        const tile = document.createElement('div');
        tile.classList.add('tile');
        tile.id = `tile-${escapeEmailSelector(email)}`;

        // Add click event to copy email and OTP to clipboard
        tile.onclick = () => copyToClipboard(email);

        // Extract the part before '@' and display it
        const emailPrefix = email.split('@')[0];
        const emailElem = document.createElement('h4');
        emailElem.textContent = emailPrefix; // Display only the part before '@'
        tile.appendChild(emailElem);

        const dateElem = document.createElement('p');
        dateElem.id = `date-${escapeEmailSelector(email)}`;
        dateElem.textContent = 'Date: Fetching...';
        tile.appendChild(dateElem);

        const timeElem = document.createElement('p');
        timeElem.id = `time-${escapeEmailSelector(email)}`;
        timeElem.textContent = 'Time: Fetching...';
        tile.appendChild(timeElem);

        const otpElem = document.createElement('p');
        otpElem.id = `otp-${escapeEmailSelector(email)}`;
        otpElem.textContent = 'OTP: Fetching...';
        tile.appendChild(otpElem);

        const deleteButton = document.createElement('button');
        deleteButton.classList.add('delete-btn');
        deleteButton.textContent = 'Remove';
        deleteButton.onclick = (e) => {
            e.stopPropagation(); // Prevent tile click event
            deleteEmail(email);
        };
        tile.appendChild(deleteButton);

        tilesContainer.appendChild(tile);
    });

    if (selectedEmails.size === 0) {
        clearInterval(otpRefreshInterval);
        clearTimeout(refreshTimeout);
    }
}

// Copy email and OTP to clipboard
function copyToClipboard(email) {
    const otpElem = document.getElementById(`otp-${escapeEmailSelector(email)}`);
    if (otpElem) {
        const otpText = otpElem.textContent;
        const otp = otpText.includes(': ') ? otpText.split(': ')[1] : null;

        if (otp) {
            navigator.clipboard.writeText(`${email}\n${otp}`).then(() => {
                console.log('Copied to clipboard');
                const tile = document.getElementById(`tile-${escapeEmailSelector(email)}`);
                if (tile) tile.style.backgroundColor = '#f9f9f9'; // Reset tile color
            });
        } else {
            console.error(`OTP is undefined for email: ${email}`);
        }
    } else {
        console.error(`OTP element not found for email: ${email}`);
    }
}


// Fetch OTPs for selected emails
function fetchOTPs() {
    const emails = Array.from(selectedEmails);
    if (!emails.length) return;

    fetch('/api/get_otps', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email_ids: emails })
    })
    .then(response => response.json())
    .then(data => {
        Object.keys(data.otps || {}).forEach(email => {
            const otpData = data.otps[email];
            if (otpData) {
                const { otp, date, time } = otpData;
                const otpElem = document.getElementById(`otp-${escapeEmailSelector(email)}`);
                const previousOtp = otpElem.textContent.split(': ')[1]; // Extract the previous OTP

                otpElem.textContent = `OTP: ${otp}`;
                document.getElementById(`date-${escapeEmailSelector(email)}`).textContent = `Date: ${date}`;
                document.getElementById(`time-${escapeEmailSelector(email)}`).textContent = `Time: ${time}`;
                const tile = document.getElementById(`tile-${escapeEmailSelector(email)}`);
                if (tile) {
                    if (otp !== previousOtp) {
                        tile.style.backgroundColor = '#d4edda'; // Set green background for new OTP
                    }
                }
            }
        });
    })
    .catch(error => console.error("Error fetching OTPs:", error));
}

// Delete email from the selected list
function deleteEmail(email) {
    selectedEmails.delete(email);
    const tile = document.getElementById(`tile-${escapeEmailSelector(email)}`);
    if (tile) tile.remove();

    if (selectedEmails.size === 0) {
        clearInterval(otpRefreshInterval);
        clearTimeout(refreshTimeout);
    }
}

// Initialize email fetching on page load
$(document).ready(loadEmailIDs);

// Start OTP fetch with a 10-second delay
function waitAndFetchOTPs() {
    refreshTimeout = setTimeout(fetchOTPs, 20000); // 10-second delay
    startOTPRefresh(); // Start OTP refresh immediately
}

// Start refreshing OTPs every 10 seconds
function startOTPRefresh() {
    otpRefreshInterval = setInterval(fetchOTPs, 20000); // Refresh OTPs every 10 seconds
}
