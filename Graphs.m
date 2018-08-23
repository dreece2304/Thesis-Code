%% Graph Production
% This script will be split into multiple sections that when run
% individually will create desired graphs for the results section of the
% thesis

%% SOC Model Comparison
clf
tt_h = tt/3600;hold on;
Ts = [1:86400]/3600;
plot(tt_h,SOC,Ts,SOC1(1:length(Ts)),'r')
xlabel('Time [Hours]'); ylabel('SOC'); title('Simulated SOC Profile with Both Models');
legend('Equivalent Circuit Model SOC Profile','Energy Flow Model SOC Profile','location','southeast')


%% Baseline Case
%% NPV
clf

% Create figure
figure1 = figure;

% Create axes
axes1 = axes('Parent',figure1);
hold(axes1,'on');
% Cash Flow until death
Y1 = (NPV_Out.Cash/1000000);
[x0,y0] =intersections(NPV_Out.Month, Y1,[0 80],[0 0]); % Calculate paypack period
plot(NPV_Out.Month, Y1,[0 80],[0 0],'r--')
xlabel('Time [Month]'); ylabel('NPV [M$]');
title('Cash Flow of Baseline Case');


box(axes1,'on');
grid(axes1,'on');
% Create textarrow
ta1 = annotation(figure1,'textarrow',[0.8 0.7],...
    [0.640063694267516 0.79]);
ta1.String = 'PP = 25 Months';            % set the text for the first annotation
ta1.HorizontalAlignment = 'center';
%% P OUT and SOC
t = [1:1000000];
pointsize = 5;
scatter(Fr(t),P_output1(t),pointsize, SOC1(t))
xlabel('Grid Frequency (Hz)') ; ylabel('Power Output (MW)');
title('Estimation of Required Power Output');
h = colorbar; set(get(h,'label'),'string','State of Charge (%)');

%% Degradation Curve

poly = polyfit([1:n],SOH,1);
%plot([1:n],SOH)
hold on 
x = [1:5:(0.2/(L/12))];
plot(x,polyval(poly,x),'rx','DisplayName','Fitted'); hold off;

grid on
box on
xlabel('Time [Months]');ylabel('SOH');title('SOH of Battery');

%% SOC and Power Profile 
% Show sample period of 1 hour
clf
T = [1:10800]./3600;
subplot(1,2,1)
plot(T,SOC1(1:length(T)))
xlabel('Time [Hours]');ylabel('SOC'); title('SOC of Battery vs Time');
xlim([0 3])
ylim([0.2 0.8])
grid on 
box on

subplot(1,2,2)
plot(T,P_output1(1:length(T)))
xlabel('Time [Hours]');ylabel('Power Output [MW]'); title('Power Output of Battery vs Time');
xlim([0 3])
ylim([-5 5])
grid on
box on



%% NON-BASELINE







